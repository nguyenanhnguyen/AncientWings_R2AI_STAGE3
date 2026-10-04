from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing
import os
import random
import re
import signal
import socket
import ssl
import sys
import time
from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import aiohttp
import polars as pl

from common import (MAX_TEXT_CHARS, RETRYABLE, domain_of_host, guess_lang, host_of, scan_light, sha256_text,
                    text_status, utf8_console, write_shard)
from extract import extract_document

FAILURES ={"timeout", "conn_error", "dns_error", "ssl_error", "http_5xx", "robots_unreachable"}

DEFAULT_AGENT = "RoadToAI-ResearchBot"

_DNS_ERROR = getattr(aiohttp, "ClientConnectorDNSError", None)
_REDIRECT_ERRORS = tuple(
    e for e in (aiohttp.TooManyRedirects, getattr(aiohttp, "RedirectClientError", None)) if e is not None
)
_SSL_ERRORS = (aiohttp.ClientConnectorCertificateError, aiohttp.ClientSSLError, ssl.SSLError)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def short(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


def backoff(attempt: int) -> float:
    return min(30.0, 2.0 ** attempt) * random.uniform(0.5, 1.0)


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        from email.utils import parsedate_to_datetime
        delta = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta)
    except Exception:
        return None


def classify(content_type: str, url: str) -> str | None:
    c = content_type.lower()
    path = urlsplit(url).path.lower()
    if "pdf" in c or (("octet-stream" in c or not c) and path.endswith(".pdf")):
        return "pdf"
    if not c or "html" in c or "xml" in c:
        return "html"
    if c.startswith("text/plain"):
        return "text"
    return None


def _ignore_sigint() -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)


class Gate:
    __slots__ = ("interval", "base", "next_time", "lock", "fails", "tripped", "delay_applied")

    def __init__(self, interval: float):
        self.interval = interval
        self.base = interval
        self.next_time = 0.0
        self.lock = asyncio.Lock()
        self.fails = 0
        self.tripped = False
        self.delay_applied = False

    async def wait(self) -> None:
        loop = asyncio.get_running_loop()
        async with self.lock:
            now = loop.time()
            if self.next_time > now:
                await asyncio.sleep(self.next_time - now)
                now = loop.time()
            self.next_time = now + self.interval * random.uniform(0.9, 1.1)

    def slow_down(self, retry_after: float | None) -> None:
        self.interval = min(60.0, max(self.interval * 2.0, retry_after or 0.0))
        loop = asyncio.get_running_loop()
        self.next_time = max(self.next_time, loop.time() + (retry_after or self.interval))

    def crawl_delay(self, seconds: float, cap: float) -> None:
        if not self.delay_applied:
            self.delay_applied = True
            self.base = max(self.base, min(seconds, cap))
            self.interval = max(self.interval, self.base)

    def success(self) -> None:
        self.fails = 0
        if self.interval > self.base:
            self.interval = max(self.base, self.interval * 0.9)

    def failure(self, trip_after: int) -> bool:
        self.fails += 1
        if not self.tripped and self.fails >= trip_after:
            self.tripped = True
            return True
        return False


class Robots:
    def __init__(self, crawler: "Crawler"):
        self.c = crawler
        self.rounds = max(1, crawler.args.robots_rounds)
        self.wait = max(1.0, crawler.args.robots_wait)
        self.cache: dict[str, tuple[str, RobotFileParser | None, float, str, int]] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    async def check(self, url: str, gate: Gate) -> tuple[str, float | None, str]:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        lock = self.locks.get(origin)
        if lock is None:
            lock = self.locks[origin] = asyncio.Lock()
        async with lock:
            entry = self.cache.get(origin)
            if entry is None:
                entry = await self.fetch(origin, gate, 1)
            elif entry[0] in ("unreachable", "conn_error"):
                age = time.monotonic() - entry[2]
                if entry[4] < self.rounds and age >= self.wait:
                    entry = await self.fetch(origin, gate, entry[4] + 1)
                elif entry[4] >= self.rounds and age > 1800:
                    entry = await self.fetch(origin, gate, 1)
            self.cache[origin] = entry
        state, parser, fetched, detail, rounds = entry
        if state == "parsed":
            agent = self.c.robots_agent
            if not parser.can_fetch(agent, url):
                return "disallow", None, ""
            delay = parser.crawl_delay(agent)
            return "allow", float(delay) if delay else None, ""
        if state == "allow":
            return "allow", None, ""
        if rounds < self.rounds:
            return "wait", max(1.0, self.wait - (time.monotonic() - fetched)), detail
        return state, None, detail

    async def fetch(self, origin: str, gate: Gate, rounds: int) -> tuple[str, RobotFileParser | None, float, str, int]:
        state, detail = await self._fetch_once(origin, gate)
        if state in ("parsed", "allow"):
            if rounds > 1:
                print(f"  ~ {origin}: robots.txt ok on round {rounds}, crawling")
            return state, detail, time.monotonic(), "", rounds
        if rounds < self.rounds:
            print(f"  ~ {origin}: robots.txt failed ({detail}), pausing this site {self.wait:g}s "
                  f"before trying again (round {rounds}/{self.rounds})")
        else:
            print(f"  ! {origin}: robots.txt still failing after {rounds} rounds ({detail}); "
                  f"its urls are marked robots_unreachable (retry later with --retry-failed)")
        return state, None, time.monotonic(), detail, rounds

    async def _fetch_once(self, origin: str, gate: Gate) -> tuple[str, RobotFileParser | str]:
        url = origin + "/robots.txt"
        state, detail = "unreachable", ""
        for attempt in range(3):
            await gate.wait()
            try:
                code, body = await self.c.get_small(url, limit=512_000)
            except _SSL_ERRORS as exc:
                state, detail = "unreachable", short(exc)
            except asyncio.TimeoutError:
                state, detail = "unreachable", f"timeout after {self.c.args.timeout:g}s"
            except aiohttp.ClientConnectorError as exc:
                state, detail = "conn_error", short(exc)
            except (aiohttp.ClientError, OSError, ValueError) as exc:
                state, detail = "unreachable", short(exc)
            else:
                if 200 <= code < 300:
                    rp = RobotFileParser()
                    rp.parse(body.decode("utf-8", errors="ignore").splitlines())
                    return "parsed", rp
                if 400 <= code < 500 and code != 429:
                    return "allow", None
                state, detail = "unreachable", f"HTTP {code}"
            if attempt < 2:
                await asyncio.sleep(2.0 + 3.0 * attempt)
        return state, detail


class Crawler:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.worker = re.sub(r"[^A-Za-z0-9_-]+", "-", args.worker or socket.gethostname())[:40] or "worker"
        self.robots_agent = args.robots_agent
        self.session_tag = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.batch_no = args.batch if args.batch is not None else -1
        if args.out:
            self.out_dir = Path(args.out)
        elif args.batch is not None:
            self.out_dir = Path(args.out_root) / f"batch_{args.batch:02d}"
        else:
            self.out_dir = Path(args.out_root) / Path(args.input).stem
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.retry_statuses = set(RETRYABLE) if args.retry_failed else set()
        if args.retry_status:
            self.retry_statuses |= {s.strip() for s in args.retry_status.split(",") if s.strip()}
        self.buffer: list[dict] = []
        self.pending: set = set()
        self.seq = 0
        self.counts: Counter = Counter()
        self.session_done = 0
        self.done_before = 0
        self.total = 0
        self.queues: dict[str, deque] = {}
        self.gates: dict[str, Gate] = {}
        self.active = 0
        self.pool: ProcessPoolExecutor | None = None
        self.session: aiohttp.ClientSession | None = None
        self.started = time.monotonic()
        self.extract_workers = args.extract_workers or max(1, (os.cpu_count() or 2) - 1)

    def load_input(self) -> pl.DataFrame:
        a = self.args
        path = Path(a.input) if a.input else Path(a.batches_dir) / f"batch_{a.batch:02d}.parquet"
        if not path.exists():
            sys.exit(f"input not found: {path}")
        df = pl.read_parquet(path)
        missing = {"id", "url"} - set(df.columns)
        if missing:
            sys.exit(f"{path} is missing columns {missing}")
        if "host" not in df.columns:
            df = df.with_columns(pl.col("url").map_elements(host_of, return_dtype=pl.String).alias("host"))
        if "domain" not in df.columns:
            df = df.with_columns(pl.col("host").map_elements(domain_of_host, return_dtype=pl.String).alias("domain"))
        if a.ids_file:
            ids = [int(x) for x in Path(a.ids_file).read_text(encoding="utf-8").split() if x.strip().lstrip("-").isdigit()]
            df = df.filter(pl.col("id").is_in(ids))
        if a.domains:
            wanted = [d.strip().lower() for d in a.domains.split(",") if d.strip()]
            df = df.filter(pl.col("domain").is_in(wanted) | pl.col("host").is_in(wanted))
        if a.skip_domains:
            skip = [d.strip().lower() for d in a.skip_domains.split(",") if d.strip()]
            df = df.filter(~(pl.col("domain").is_in(skip) | pl.col("host").is_in(skip)))
        if a.limit:
            df = df.head(a.limit)
        return df.select("id", "url", "host", "domain").filter(pl.col("url").is_not_null())

    def load_done(self) -> set[int]:
        files = sorted(self.out_dir.glob("*.parquet"))
        if not files:
            return set()
        st = scan_light([str(f) for f in files], ["id", "status"])
        if st.height == 0:
            return set()
        if self.retry_statuses:
            st = st.filter(~pl.col("status").is_in(sorted(self.retry_statuses)))
        return set(st["id"].to_list())

    def prepare(self) -> bool:
        df = self.load_input()
        done = self.load_done()
        n_input = df.height
        if done:
            df = df.filter(~pl.col("id").is_in(list(done)))
        self.done_before = n_input - df.height
        self.total = n_input
        key = "host" if self.args.rate_key == "host" else "domain"
        groups = df.group_by(key, maintain_order=True).agg("id", "url")
        for dom, ids, urls in groups.iter_rows():
            self.queues.setdefault(dom or "_unknown", deque()).extend(zip(ids, urls))
        print(f"input: {n_input:,} ids | already done: {self.done_before:,} | to crawl now: {df.height:,} "
              f"across {len(self.queues):,} {key}s | output: {self.out_dir}")
        if df.height == 0:
            print("nothing to do")
            return False
        biggest = sorted(self.queues.items(), key=lambda kv: -len(kv[1]))[:5]
        for dom, q in biggest:
            days = len(q) * self.args.interval / 86_400
            print(f"  {dom[:45]:<45} {len(q):>9,} urls  (~{days:.1f} days at {self.args.interval}s per request)")
        return True

    def next_path(self) -> Path:
        self.seq += 1
        return self.out_dir / f"part-{self.worker}-{self.session_tag}-{self.seq:05d}.parquet"

    def record(self, rid: int, url: str, domain: str, status: str, **kw) -> None:
        text = (kw.get("text") or "")[:MAX_TEXT_CHARS]
        self.buffer.append({
            "id": rid,
            "url": url,
            "final_url": kw.get("final_url") or "",
            "domain": domain,
            "status": status,
            "http_status": kw.get("http_status"),
            "content_type": (kw.get("content_type") or "")[:200],
            "title": (kw.get("title") or "")[:1000],
            "text": text,
            "lang": kw.get("lang") or "",
            "n_chars": len(text),
            "html": kw.get("html") or None,
            "error": (kw.get("error") or "")[:300],
            "fetched_at": now_iso(),
            "worker": self.worker,
            "batch": self.batch_no,
            "extractor": kw.get("extractor") or "",
            "published_at": kw.get("published_at") or "",
            "text_sha256": sha256_text(text),
        })
        self.counts[status] += 1
        self.session_done += 1
        if len(self.buffer) >= self.args.shard_size:
            rows, self.buffer = self.buffer, []
            fut = asyncio.get_running_loop().run_in_executor(None, write_shard, rows, self.next_path())
            self.pending.add(fut)
            fut.add_done_callback(self.pending.discard)

    def flush_sync(self) -> None:
        if self.buffer:
            rows, self.buffer = self.buffer, []
            write_shard(rows, self.next_path())

    async def get_small(self, url: str, limit: int) -> tuple[int, bytes]:
        insecure = False
        while True:
            try:
                async with self.net_sem:
                    async with self.session.get(url, ssl=False if insecure else None, allow_redirects=True,
                                                max_redirects=5) as resp:
                        chunks, size = [], 0
                        if resp.status == 200:
                            async for chunk in resp.content.iter_chunked(65_536):
                                chunks.append(chunk)
                                size += len(chunk)
                                if size >= limit:
                                    break
                        return resp.status, b"".join(chunks)[:limit]
            except _SSL_ERRORS:
                if self.args.strict_ssl or insecure:
                    raise
                insecure = True

    async def fetch_page(self, url: str, gate: Gate) -> dict:
        attempts = 0
        insecure = False
        last: dict = {"status": "error"}
        while attempts <= self.args.retries:
            await gate.wait()
            code, final, ctype, retry_after = 0, url, "", None
            try:
                async with self.net_sem:
                    async with self.session.get(url, ssl=False if insecure else None, allow_redirects=True,
                                                max_redirects=8) as resp:
                        code = resp.status
                        final = str(resp.url)
                        ctype = resp.headers.get("Content-Type", "")
                        if code == 200:
                            kind = classify(ctype, final)
                            base = {"http_status": code, "final_url": final, "content_type": ctype}
                            if kind is None:
                                return {"status": "skipped_type", **base}
                            if resp.content_length and resp.content_length > self.max_bytes:
                                return {"status": "too_large", **base}
                            chunks, size = [], 0
                            async for chunk in resp.content.iter_chunked(65_536):
                                size += len(chunk)
                                if size > self.max_bytes:
                                    return {"status": "too_large", **base}
                                chunks.append(chunk)
                            body = b"".join(chunks)
                            if kind == "html" and body[:5] == b"%PDF-":
                                kind = "pdf"
                            note = "tls not verified" if insecure else ""
                            return {"status": "fetched", "kind": kind, "body": body, "error": note, **base}
                        retry_after = parse_retry_after(resp.headers.get("Retry-After"))
            except _SSL_ERRORS as exc:
                if not self.args.strict_ssl and not insecure:
                    insecure = True
                    continue
                last = {"status": "ssl_error", "error": short(exc)}
                attempts += 1
            except asyncio.TimeoutError:
                last = {"status": "timeout", "error": "timeout"}
                attempts += 1
            except _REDIRECT_ERRORS as exc:
                return {"status": "http_other", "error": short(exc)}
            except (aiohttp.InvalidURL, ValueError) as exc:
                return {"status": "bad_url", "error": short(exc)}
            except aiohttp.ClientConnectorError as exc:
                if _DNS_ERROR is not None and isinstance(exc, _DNS_ERROR):
                    return {"status": "dns_error", "error": short(exc)}
                last = {"status": "conn_error", "error": short(exc)}
                attempts += 1
            except (aiohttp.ClientError, OSError) as exc:
                last = {"status": "conn_error", "error": short(exc)}
                attempts += 1
            else:
                base = {"http_status": code, "final_url": final, "content_type": ctype}
                if code in (429, 503):
                    gate.slow_down(retry_after)
                    last = {"status": "rate_limited" if code == 429 else "http_5xx", **base}
                    attempts += 1
                    continue
                if code >= 500:
                    last = {"status": "http_5xx", **base}
                    attempts += 1
                elif code in (404, 410):
                    return {"status": "not_found", **base}
                elif code in (401, 403, 451):
                    return {"status": "blocked", **base}
                elif code >= 400:
                    return {"status": "http_4xx", **base}
                else:
                    return {"status": "http_other", **base}
            if attempts <= self.args.retries:
                await asyncio.sleep(backoff(attempts))
        return last

    async def process(self, rid: int, url: str, dom: str, gate: Gate) -> float | None:
        if gate.tripped:
            self.record(rid, url, dom, "domain_skipped")
            return None
        try:
            state, delay, detail = await self.robots.check(url, gate)
        except Exception as exc:
            state, delay, detail = "unreachable", None, short(exc)
        if state == "wait":
            return delay
        if state == "disallow":
            self.record(rid, url, dom, "robots_disallowed")
            return
        if state in ("unreachable", "conn_error"):
            status = "robots_unreachable" if state == "unreachable" else "conn_error"
            self.record(rid, url, dom, status, error=f"robots.txt: {detail or 'could not be fetched'}")
            self.note_failure(dom, gate)
            return
        if delay:
            gate.crawl_delay(delay, self.args.max_crawl_delay)

        res = await self.fetch_page(url, gate)
        status = res.pop("status")
        if status != "fetched":
            if status in FAILURES:
                self.note_failure(dom, gate)
            else:
                gate.success()
            self.record(rid, url, dom, status, **res)
            return

        gate.success()
        body = res.pop("body")
        kind = res.pop("kind")
        loop = asyncio.get_running_loop()
        async with self.extract_sem:
            try:
                ex = await loop.run_in_executor(
                    self.pool, extract_document, body, res["final_url"], kind, not self.args.no_html,
                    res.get("content_type") or "")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self.stopping:
                    return
                ex = {"title": "", "text": "", "html": b"", "error": short(exc)}
        if ex["error"]:
            self.record(rid, url, dom, "extract_error", html=ex["html"], error=ex["error"],
                        **{k: v for k, v in res.items() if k != "error"})
            return
        text = ex["text"]
        status = text_status(text, ex["extractor"], self.args.min_chars)
        self.record(rid, url, dom, status, title=ex["title"], text=text, html=ex["html"], lang=guess_lang(text),
                    extractor=ex["extractor"], published_at=ex["published_at"], **res)

    def note_failure(self, dom: str, gate: Gate) -> None:
        if gate.failure(self.args.trip_after):
            left = len(self.queues.get(dom, ()))
            print(f"  ! {dom}: {gate.fails} consecutive failures, skipping its remaining {left:,} urls "
                  f"(status domain_skipped, retry later with --retry-failed)")

    async def run_domain(self, dom: str, items: deque) -> None:
        gate = self.gates.get(dom)
        if gate is None:
            gate = self.gates[dom] = Gate(self.args.interval)

        async def sub() -> None:
            while items:
                rid, url = items.popleft()
                wait = await self.process(rid, url, dom, gate)
                if wait:
                    items.append((rid, url))
                    await asyncio.sleep(wait)

        await asyncio.gather(*(sub() for _ in range(max(1, min(self.args.per_domain, len(items))))))

    def progress_line(self, rate_now: float) -> str:
        done = self.done_before + self.session_done
        pct = 100.0 * done / max(1, self.total)
        elapsed = time.monotonic() - self.started
        avg = self.session_done / max(1.0, elapsed)
        ok = self.counts.get("ok", 0)
        ok_pct = 100.0 * ok / max(1, self.session_done)
        remaining = self.total - done
        eta = remaining / rate_now / 3600 if rate_now > 0 else float("inf")
        h, rem = divmod(int(elapsed), 3600)
        m, s = divmod(rem, 60)
        return (f"[{h:02d}:{m:02d}:{s:02d}] {done:,}/{self.total:,} ({pct:.1f}%) | {rate_now:.1f} pages/s now, "
                f"{avg:.1f} avg | ok {ok_pct:.0f}% | active domains {self.active} | ETA ~{eta:.1f}h at current speed")

    async def report_loop(self) -> None:
        last_n, last_t = 0, time.monotonic()
        while True:
            await asyncio.sleep(self.args.report_every)
            now = time.monotonic()
            rate = (self.session_done - last_n) / max(1e-6, now - last_t)
            last_n, last_t = self.session_done, now
            print(self.progress_line(rate))
            top = ", ".join(f"{k} {v:,}" for k, v in self.counts.most_common(6))
            print(f"    status: {top}")
            big = sorted(((d, len(q)) for d, q in self.queues.items() if q), key=lambda x: -x[1])[:3]
            if big:
                parts = []
                for d, n in big:
                    g = self.gates.get(d)
                    iv = g.interval if g else self.args.interval
                    parts.append(f"{d} {n:,} left (~{n * iv / 3600:.1f}h at {iv:.2g}s/request)")
                print(f"    biggest queues: {'; '.join(parts)}")
            try:
                (self.out_dir / f"progress-{self.worker}.json").write_text(json.dumps({
                    "worker": self.worker, "batch": self.batch_no, "updated": now_iso(),
                    "total": self.total, "done": self.done_before + self.session_done,
                    "session_done": self.session_done, "rate_now": round(rate, 2),
                    "counts": dict(self.counts),
                }, indent=1), encoding="utf-8")
            except OSError:
                pass

    async def run(self) -> None:
        a = self.args
        self.stopping = False
        self.max_bytes = int(a.max_mb * 1024 * 1024)
        self.net_sem = asyncio.Semaphore(a.concurrency)
        self.extract_sem = asyncio.Semaphore(max(4, 4 * self.extract_workers))
        connector = aiohttp.TCPConnector(limit=a.concurrency, limit_per_host=a.per_domain + 1,
                                         ttl_dns_cache=600)
        timeout = aiohttp.ClientTimeout(total=a.timeout, connect=min(15.0, a.timeout), sock_read=a.timeout)
        headers = {
            "User-Agent": a.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.8,*/*;q=0.5",
            "Accept-Language": "vi,en;q=0.8,zh;q=0.6",
        }
        async with aiohttp.ClientSession(connector=connector, timeout=timeout, headers=headers,
                                         trust_env=a.trust_env) as session:
            self.session = session
            self.robots = Robots(self)
            order = deque(sorted(self.queues.items(), key=lambda kv: -len(kv[1])))

            async def runner() -> None:
                while order:
                    dom, items = order.popleft()
                    self.active += 1
                    try:
                        await self.run_domain(dom, items)
                    finally:
                        self.active -= 1

            reporter = asyncio.create_task(self.report_loop())
            try:
                await asyncio.gather(*(runner() for _ in range(max(1, min(a.max_domains, len(order))))))
            except asyncio.CancelledError:
                self.stopping = True
                raise
            finally:
                reporter.cancel()
        if self.pending:
            await asyncio.gather(*list(self.pending), return_exceptions=True)

    def close(self) -> None:
        self.flush_sync()
        if self.pool is not None:
            self.pool.shutdown(wait=False, cancel_futures=True)

    def export_json(self, only_if_missing: bool = False) -> None:
        if self.args.no_json:
            return
        from export_json import existing_outputs, export

        json_dir = Path(self.args.json_dir)
        name = self.out_dir.name
        if only_if_missing:
            found = existing_outputs(json_dir, name)
            if found:
                more = f" (+{len(found) - 1} more)" if len(found) > 1 else ""
                print(f"JSON already written: {found[0]}{more}")
                return
        left = self.total - self.done_before - self.session_done
        if left > 0:
            print(f"JSON not written yet: it is written when the run finishes. "
                  f"To export what is crawled so far: python export_json.py --input {self.out_dir}")
            return
        export([str(self.out_dir)], json_dir, name)

    def summary(self) -> None:
        elapsed = time.monotonic() - self.started
        print(f"\nsession: {self.session_done:,} urls in {elapsed / 60:.1f} min | files in {self.out_dir}")
        for k, v in self.counts.most_common():
            print(f"  {k:<20} {v:>9,}")
        left = self.total - self.done_before - self.session_done
        if left > 0:
            print(f"{left:,} urls not finished yet; run the same command again to continue")


def run_async(coro):
    if sys.platform == "win32":
        if sys.version_info >= (3, 12):
            return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(coro)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Polite crawler for one batch of links_corpus ids.")
    src = ap.add_argument_group("input / output")
    src.add_argument("--batch", type=int, help="batch number from make_batches.py (reads batches/batch_XX.parquet)")
    src.add_argument("--input", help="any parquet with id,url columns instead of --batch")
    src.add_argument("--batches-dir", default="batches")
    src.add_argument("--out-root", default="crawl_out")
    src.add_argument("--out", help="explicit output folder (default crawl_out/batch_XX)")
    src.add_argument("--worker", default="", help="your name, written into every row and file name")
    src.add_argument("--ids-file", help="only crawl ids listed in this text file (one per line)")
    src.add_argument("--domains", help="only crawl these domains (comma separated)")
    src.add_argument("--skip-domains", help="leave these domains out for now (comma separated)")
    src.add_argument("--limit", type=int, default=0, help="only the first N ids (for a quick test)")
    src.add_argument("--retry-failed", action="store_true", help="crawl again ids whose earlier result was a temporary failure")
    src.add_argument("--retry-status", default="", help="extra statuses to crawl again, comma separated (e.g. blocked)")
    src.add_argument("--no-html", action="store_true", help="do not keep the (slimmed) HTML; saves disk")
    src.add_argument("--no-json", action="store_true", help="do not write the JSON copy when the run finishes")
    src.add_argument("--json-dir", default="json_out", help="folder for the JSON copy of the results")

    pol = ap.add_argument_group("politeness and speed")
    pol.add_argument("--interval", type=float, default=1.0, help="seconds between requests to the same domain")
    pol.add_argument("--per-domain", type=int, default=2, help="max parallel requests to one domain")
    pol.add_argument("--concurrency", type=int, default=64, help="max parallel requests overall")
    pol.add_argument("--max-domains", type=int, default=500, help="domains crawled at the same time")
    pol.add_argument("--rate-key", choices=["domain", "host"], default="domain",
                     help="limit speed per registered domain (default, safer) or per host name")
    pol.add_argument("--max-crawl-delay", type=float, default=30.0, help="cap for Crawl-delay from robots.txt")
    pol.add_argument("--robots-rounds", type=int, default=3,
                     help="rounds of trying robots.txt before marking a site robots_unreachable")
    pol.add_argument("--robots-wait", type=float, default=60.0, help="seconds a site is paused between robots.txt rounds")
    pol.add_argument("--timeout", type=float, default=25.0)
    pol.add_argument("--retries", type=int, default=2)
    pol.add_argument("--trip-after", type=int, default=25, help="skip a domain after this many failures in a row")
    pol.add_argument("--user-agent", default=f"Mozilla/5.0 (compatible; {DEFAULT_AGENT}/1.0; academic research crawler)")
    pol.add_argument("--robots-agent", default=DEFAULT_AGENT, help="name matched against robots.txt rules")
    pol.add_argument("--strict-ssl", action="store_true", help="do not retry without certificate checks on TLS errors")
    pol.add_argument("--trust-env", action="store_true", help="use HTTP(S)_PROXY from the environment")

    misc = ap.add_argument_group("processing")
    misc.add_argument("--max-mb", type=float, default=8.0, help="skip responses larger than this")
    misc.add_argument("--min-chars", type=int, default=100, help="below this many characters the status is empty_text")
    misc.add_argument("--extract-workers", type=int, default=0, help="processes for text extraction (default: CPUs - 1)")
    misc.add_argument("--shard-size", type=int, default=1000, help="rows per output file")
    misc.add_argument("--report-every", type=float, default=30.0, help="seconds between progress lines")
    args = ap.parse_args()
    if args.batch is None and not args.input:
        ap.error("give --batch N or --input FILE")
    if sys.platform == "win32" and args.concurrency > 400:
        print("windows: lowering --concurrency to 400")
        args.concurrency = 400
    return args


def main() -> None:
    utf8_console()
    args = parse_args()
    crawler = Crawler(args)
    if not crawler.prepare():
        crawler.export_json(only_if_missing=True)
        return
    crawler.pool = ProcessPoolExecutor(max_workers=crawler.extract_workers,
                                       mp_context=multiprocessing.get_context("spawn"),
                                       initializer=_ignore_sigint)
    try:
        run_async(crawler.run())
    except KeyboardInterrupt:
        print("\nstopped by user, saving what was crawled...")
    finally:
        crawler.close()
        crawler.summary()
    crawler.export_json()


if __name__ == "__main__":
    main()
