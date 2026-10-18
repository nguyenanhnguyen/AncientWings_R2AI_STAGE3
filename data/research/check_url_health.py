"""Read-only, reproducible HTTP spot check of the eight supplied corpus sources.

Reads the pinned Parquet snapshot; writes evidence only under the output folder.
An HTTP success is not a guarantee that the crawler extracts a usable article.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random
import re
import time
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow.parquet as pq
import requests
from lxml import html


SOURCES = {
    "pubmed.ncbi.nlm.nih.gov": 240000,
    "suckhoecongdongonline.vn": 154503,
    "www.120ask.com": 98160,
    "suckhoedoisong.vn": 85823,
    "nhathuoclongchau.com.vn": 79598,
    "thanhnien.vn": 72111,
    "www.vinmec.com": 26129,
    "medlatec.vn": 24762,
}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
DEAD_PAGE = re.compile(
    r"(?:^|\b)(?:404|410)(?:\b|$)|page not found|not found|không tìm thấy|"
    r"trang không tồn tại|trang lỗi|页面不存在|页面未找到|找不到页面", re.I
)
CHALLENGE = re.compile(
    r"just a moment|checking your browser|verify (?:that )?you are human|"
    r"access denied|403 forbidden|security verification|please enable javascript.*continue|"
    r"您访问过于频繁|访问被拒绝|安全验证", re.I
)


def now():
    return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(timespec="seconds")


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sample_source(path, sample_size, seed):
    counts = Counter()
    schemes = {host: Counter() for host in SOURCES}
    homepage_counts = Counter()
    samples = {host: [] for host in SOURCES}
    generators = {host: random.Random(f"{seed}:{host}") for host in SOURCES}
    for batch in pq.ParquetFile(path).iter_batches(batch_size=65536, columns=["id", "url"]):
        for row in batch.to_pylist():
            parsed = urlsplit(row["url"] or "")
            host = (parsed.hostname or "").lower()
            if host not in SOURCES:
                continue
            counts[host] += 1
            schemes[host][parsed.scheme] += 1
            homepage_counts[host] += parsed.path in ("", "/", "/vie", "/vie/")
            row["domain"] = host
            reservoir = samples[host]
            if len(reservoir) < sample_size:
                reservoir.append(row)
            else:
                index = generators[host].randrange(counts[host])
                if index < sample_size:
                    reservoir[index] = row
    structure = {
        host: {"expected_count": expected, "actual_count": counts[host],
               "schemes": dict(schemes[host]), "homepage_urls": homepage_counts[host]}
        for host, expected in SOURCES.items()
    }
    return {host: sorted(rows, key=lambda row: row["id"]) for host, rows in samples.items()}, structure


def request_once(session, url, connect_timeout=7, read_timeout=12):
    started = time.monotonic()
    result = {"requested_url": url, "checked_at": now(), "http_status": None,
              "final_url": "", "redirects": [], "classification": "", "error": "",
              "title": "", "h1": "", "body_bytes": 0, "body_truncated": False,
              "text_preview": ""}
    try:
        with session.get(url, timeout=(connect_timeout, read_timeout), stream=True, allow_redirects=True) as response:
            result.update(http_status=response.status_code, final_url=response.url,
                          redirects=[{"status": item.status_code, "url": item.url,
                                      "location": item.headers.get("Location", "")}
                                     for item in response.history],
                          content_type=response.headers.get("Content-Type", ""))
            body = bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body) >= 3 * 1024 * 1024 or time.monotonic() - started > 30:
                    result["body_truncated"] = True
                    break
            result["body_bytes"] = len(body)
            if body and ("html" in result["content_type"] or b"<html" in body[:1000].lower()):
                try:
                    parser = html.HTMLParser(encoding=response.encoding if response.encoding and response.encoding.lower() != "iso-8859-1" else None)
                    tree = html.fromstring(bytes(body), parser=parser)
                    result["title"] = " ".join(tree.xpath("//title/text()")).strip()[:500]
                    result["h1"] = " ".join(tree.xpath("//h1//text()")).strip()[:500]
                    for node in tree.xpath("//script|//style|//noscript"):
                        node.drop_tree()
                    result["text_preview"] = re.sub(r"\s+", " ", tree.text_content()).strip()[:700]
                except (ValueError, TypeError):
                    pass
            status = response.status_code
            headings = result["title"] + " " + result["h1"]
            if status in (404, 410):
                category = "dead_http"
            elif status in (401, 403, 429, 451):
                category = "blocked_http"
            elif status >= 500 or status in (408, 425):
                category = "temporary_http"
            elif 200 <= status < 300:
                if CHALLENGE.search(headings) or "checking your browser before accessing" in result["text_preview"].lower():
                    category = "challenge_200"
                elif DEAD_PAGE.search(headings):
                    category = "suspected_soft_404"
                elif (urlsplit(url).hostname == "www.vinmec.com" and "/bai-viet/" in urlsplit(url).path
                      and not result["h1"] and result["title"].strip(" |") == "Vinmec"):
                    category = "suspected_missing_article"
                elif urlsplit(response.url).path in ("", "/", "/vie", "/vie/") and urlsplit(url).path not in ("", "/", "/vie", "/vie/"):
                    category = "redirect_homepage"
                elif not body:
                    category = "empty_body"
                else:
                    category = "http_ok"
            else:
                category = "other_http"
            result["classification"] = category
    except requests.exceptions.SSLError as error:
        result.update(classification="tls_error", error=str(error)[:700])
    except requests.exceptions.Timeout as error:
        result.update(classification="timeout", error=str(error)[:700])
    except requests.exceptions.RequestException as error:
        result.update(classification="connection_error", error=str(error)[:700])
    result["seconds"] = round(time.monotonic() - started, 3)
    return result


def probe_domain(host, rows, out, max_connection_failures=3):
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"})
    evidence = []
    connection_failures = 0
    with (out / f"{host}.jsonl").open("w", encoding="utf-8") as stream:
        for index, row in enumerate(rows, 1):
            attempts = [request_once(session, row["url"])]
            if attempts[-1]["classification"] != "http_ok":
                time.sleep(1)
                attempts.append(request_once(session, row["url"]))
            result = dict(row, **attempts[-1])
            result["attempts"] = attempts
            result["first_classification"] = attempts[0]["classification"]
            if result["classification"] != "http_ok" and urlsplit(row["url"]).scheme == "http":
                parsed = urlsplit(row["url"])
                alternate = urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))
                result["https_alternative"] = request_once(session, alternate)
            evidence.append(result)
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            stream.flush()
            if index % 10 == 0 or index == len(rows):
                print(f"{host}: {index}/{len(rows)} {dict(Counter(item['classification'] for item in evidence))}", flush=True)
            no_connection = result["http_status"] is None and result["classification"] in ("timeout", "connection_error")
            alternate_connected = result.get("https_alternative", {}).get("http_status") is not None
            connection_failures = connection_failures + 1 if no_connection and not alternate_connected else 0
            if connection_failures >= max_connection_failures:
                print(f"{host}: stop after {connection_failures} consecutive connection failures; remaining URLs untested", flush=True)
                break
            time.sleep(0.3)
    session.close()
    return evidence


def summarize(out, structure, evidence, config):
    # A separate live inspection can identify an empty article behind a 200 response.
    # Preserve original request JSONL, and apply this conclusion only to derived results.
    verification_path = out / "vinmec_suspect_verification.json"
    if verification_path.exists():
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        if verification["http_status"] == 200 and not verification["h1"] and verification["extracted_chars"] < 300:
            for item in evidence:
                if item["url"] == verification["url"] and item["classification"] == "http_ok":
                    item["http_classification"] = "http_ok"
                    item["classification"] = "suspected_missing_article"
                    item["verification_file"] = verification_path.name
    summary = dict(config, finished_at=now(), by_domain={})
    api_path = out / "pubmed_api_verification.json"
    if api_path.exists():
        api = json.loads(api_path.read_text(encoding="utf-8"))
        summary["pubmed_api_verification"] = {key: api[key] for key in ["http_status", "returned_articles", "missing_pmids", "articles_with_abstract"]}
    flat = []
    for host in SOURCES:
        records = [item for item in evidence if item["domain"] == host]
        counter = Counter(item["classification"] for item in records)
        summary["by_domain"][host] = dict(structure[host], sampled=len(records),
            planned=config['sample_per_domain'], untested=config['sample_per_domain'] - len(records),
            classifications=dict(counter), redirects=sum(bool(item["redirects"]) for item in records),
            recovered_on_retry=sum(item["first_classification"] != "http_ok" and item["classification"] == "http_ok" for item in records),
            https_alternative_ok=sum(item.get("https_alternative", {}).get("classification") == "http_ok" for item in records))
        for record in records:
            flat.append({key: record.get(key) for key in ["domain", "id", "url", "checked_at", "http_status", "classification", "first_classification", "final_url", "title", "h1", "body_bytes", "seconds", "error"]} | {
                "attempt_count": len(record["attempts"]), "redirect_count": len(record["redirects"]),
                "https_alternative_classification": record.get("https_alternative", {}).get("classification", "")})
    write_json(out / "summary.json", summary)
    frame = pd.DataFrame(flat)
    frame.to_csv(out / "url_results.csv", index=False, encoding="utf-8-sig")
    frame[frame.classification != "http_ok"].to_csv(out / "failed_or_uncertain.csv", index=False, encoding="utf-8-sig")
    lines = ["# Kiểm tra URL corpus", "", f"- Thời gian: {config['started_at']} đến {summary['finished_at']} (giờ Việt Nam).",
        f"- Nguồn: {config['source_file']}; SHA-256: `{config['source_sha256']}`.",
        f"- Kế hoạch mẫu: reservoir ngẫu nhiên {config['sample_per_domain']} URL mỗi nguồn, seed={config['seed']}; GET theo redirect, TLS được xác minh, tối đa 2 lần cho URL lỗi. Số thực kiểm tra hiển thị trong bảng; dừng nguồn nếu kết nối liên tục thất bại.",
        "- Kết quả phản ánh đường mạng/IP và user agent của máy kiểm tra. `http_ok` nghĩa là tải được phản hồi 2xx, không đảm bảo parser lấy được nội dung bài phù hợp.",
        "- Không ngoại suy tỷ lệ lỗi từ mẫu thành số link lỗi chính xác toàn corpus.", "",
        "| Nguồn | URL toàn nguồn | Mẫu | HTTP ổn, chưa thấy lỗi bài | 404/410 | Trang lỗi/rỗng 200 | Chặn/challenge | Về trang chủ | Khác |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for host, data in summary["by_domain"].items():
        c = Counter(data["classifications"])
        empty_or_error = c["suspected_soft_404"] + c["suspected_missing_article"]
        shown = c["http_ok"] + c["dead_http"] + empty_or_error + c["blocked_http"] + c["challenge_200"] + c["redirect_homepage"]
        lines.append(f"| {host} | {data['actual_count']:,} | {data['sampled']} | {c['http_ok']} | {c['dead_http']} | {empty_or_error} | {c['blocked_http'] + c['challenge_200']} | {c['redirect_homepage']} | {data['sampled'] - shown} |")
    lines += ["", "Chi tiết và lịch sử thử lại: `*.jsonl`; bảng URL: `url_results.csv`; URL lỗi hoặc chưa xác minh: `failed_or_uncertain.csv`.", "",
              "Chú ý: `suspected_soft_404`, `suspected_missing_article` và `challenge_200` là cờ kiểm tra nội dung; chưa đủ để kết luận URL chết vĩnh viễn."]
    if "pubmed_api_verification" in summary:
        api = summary["pubmed_api_verification"]
        lines += ["", f"API NCBI EFetch trả HTTP {api['http_status']}: {api['returned_articles']} bản ghi và {api['articles_with_abstract']} bản ghi có abstract; PMID thiếu: {api['missing_pmids']}. 403 từ trang PubMed không đồng nghĩa bản ghi đã bị xóa. Xem `pubmed_api_verification.json` và `pubmed_efetch.xml`."]
    if verification_path.exists():
        lines += ["", f"URL Vinmec cần kiểm tra nội dung: {verification['url']}. Hai lần GET tiếp theo vẫn HTTP 200 nhưng title chỉ `| Vinmec`, h1 rỗng; extractor trả chủ yếu thông báo chọn ngôn ngữ. Đặt Accept-Language tiếng Việt không khôi phục bài. Công cụ web trả phiên bản có bài từ cache 7 tháng trước; chưa xác minh được nội dung bài hiện tại trên đường mạng này. Xem `vinmec_suspect_verification.json` và `vinmec_suspect_vi_verification.json`."]
    for host, data in summary["by_domain"].items():
        if data["untested"]:
            lines += ["", f"Nguồn {host}: thực kiểm tra {data['sampled']}/{data['planned']} URL; {data['untested']} URL mẫu chưa thử. Dừng mở rộng vì các kiểm tra kết nối ban đầu lỗi lặp lại; không gán trạng thái lỗi cho URL chưa thử."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary["by_domain"], ensure_ascii=False, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sample-per-domain", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20261013)
    parser.add_argument("--max-domain-connection-failures", type=int, default=3)
    args = parser.parse_args()
    if args.sample_per_domain < 1 or args.max_domain_connection_failures < 1:
        parser.error("Sample size and connection failure limit must be positive.")
    args.out.mkdir(parents=True, exist_ok=True)
    if (args.out / "samples.json").exists():
        raise SystemExit("Output already contains a probe; choose a new directory.")
    samples, structure = sample_source(args.source, args.sample_per_domain, args.seed)
    config = {"started_at": now(), "source_file": str(args.source),
        "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "sample_per_domain": args.sample_per_domain, "seed": args.seed,
        "max_domain_connection_failures": args.max_domain_connection_failures,
        "user_agent": USER_AGENT, "requested_sources": SOURCES}
    write_json(args.out / "config.json", config)
    write_json(args.out / "samples.json", samples)
    write_json(args.out / "source_structure.json", structure)
    evidence = []
    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        futures = {pool.submit(probe_domain, host, rows, args.out, args.max_domain_connection_failures): host for host, rows in samples.items()}
        for future in as_completed(futures):
            evidence.extend(future.result())
    summarize(args.out, structure, evidence, config)


if __name__ == "__main__":
    main()
