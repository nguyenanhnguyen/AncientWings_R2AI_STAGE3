from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_sites  # noqa: E402

PLANS = {
    "vi": [("bai-viet", {"ok"}, 120), ("private", {"robots_disallowed"}, 10), ("missing", {"not_found"}, 10),
           ("redirect", {"ok"}, 10), ("file", {"skipped_type"}, 5), ("limited", {"ok"}, 3),
           ("slow", {"timeout"}, 3), ("pdf", {"ok"}, 3), ("short", {"empty_text"}, 5), ("dup", {"ok"}, 5)],
    "en": [("article", {"ok"}, 120), ("blocked", {"blocked"}, 10), ("dup", {"ok"}, 5)],
    "zh": [("zh", {"ok"}, 60), ("gone", {"ok"}, 8)],
    "zhold": [("yxbk", {"ok"}, 20)],
    "flaky": [("tin", {"ok"}, 10)],
    "dead": [("page", {"robots_unreachable", "domain_skipped"}, 30)],
    "down": [("page", {"conn_error", "domain_skipped"}, 30)],
}
CRAWL_FLAGS = ["--interval", "0.02", "--per-domain", "3", "--timeout", "1.0", "--retries", "1",
               "--trip-after", "5", "--report-every", "2", "--min-chars", "20", "--extract-workers", "2",
               "--shard-size", "40", "--robots-wait", "1"]


def url_for(port: int, kind: str, n: int) -> str:
    suffix = {"file": ".png", "pdf": ".pdf"}.get(kind, "")
    return f"http://127.0.0.1:{port}/{kind}/{n}{suffix}"


def build_corpus(ports: dict[str, int], path: Path) -> dict[int, set[str]]:
    rng = random.Random(7)
    rows, expected = [], {}
    next_id = 1000
    order = ["vi", "en", "zh", "zhold", "flaky", "dead", "down"]
    for site in order:
        items = []
        for kind, exp, count in PLANS[site]:
            items += [(kind, exp, n) for n in range(count)]
        rng.shuffle(items)
        for kind, exp, n in items:
            next_id += rng.randint(1, 3)
            rows.append((next_id, url_for(ports[site], kind, n)))
            expected[next_id] = exp
    for n in range(500, 520):
        next_id += 1
        rows.append((next_id, url_for(ports["vi"], "bai-viet", n)))
        expected[next_id] = {"ok"}
    pl.DataFrame(rows, schema=["id", "url"], orient="row").write_parquet(path)
    return expected


def run(cmd: list[str], cwd: Path) -> str:
    proc = subprocess.run([sys.executable, *cmd], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=600)
    if proc.returncode != 0:
        print(proc.stdout[-3000:], proc.stderr[-3000:])
        raise SystemExit(f"command failed: {' '.join(cmd)}")
    return proc.stdout


def main() -> None:
    ap = argparse.ArgumentParser(description="End-to-end check of the crawler against local fake websites.")
    ap.add_argument("--keep", action="store_true", help="keep the temporary folder for inspection")
    args = ap.parse_args()

    profiles = ["vi", "en", "zh", "zhold", "flaky", "dead"]
    ports, stop = fake_sites.start(profiles)
    ports["down"] = fake_sites.free_port()
    work = Path(tempfile.mkdtemp(prefix="rtai-selftest-"))
    failures: list[str] = []
    t0 = time.time()
    try:
        (work / "data").mkdir()
        expected = build_corpus(ports, work / "data" / "links_corpus.parquet")
        print(f"fake corpus: {len(expected)} urls on {len(ports)} fake sites | folder {work}")

        out = run([str(ROOT / "make_batches.py"), "--batch-size", "170", "--people", "an,binh,chi"], work)
        n_batches = len(list((work / "batches").glob("batch_*.parquet")))
        print(f"[1] make_batches: {n_batches} batches")
        if n_batches != 3:
            failures.append(f"expected 3 batches, got {n_batches}")

        crawl = [str(ROOT / "crawl.py"), *CRAWL_FLAGS]
        run([*crawl, "--batch", "0", "--worker", "an", "--limit", "60"], work)
        out = run([*crawl, "--batch", "0", "--worker", "an"], work)
        resumed = "already done: 60" in out
        print(f"[2] batch 0 crawled in two runs, resume {'ok' if resumed else 'FAILED'}")
        if not resumed:
            failures.append("second run of batch 0 did not resume from the first")
        b0 = work / "json_out" / "batch_00.json"
        raw0 = b0.read_text(encoding="utf-8") if b0.exists() else "[]"
        rows0 = json.loads(raw0)
        json_ok = len(rows0) == 170 and len({r["id"] for r in rows0}) == 170 and "sỏi thận" in raw0
        print(f"    JSON written after the crawl: {len(rows0)} records in json_out/batch_00.json: "
              f"{'ok' if json_ok else 'FAILED'}")
        if not json_ok:
            failures.append("json_out/batch_00.json is missing, incomplete or not readable UTF-8")

        if sys.platform != "win32":
            proc = subprocess.Popen([sys.executable, *crawl, "--batch", "1", "--worker", "binh", "--interval", "0.3"],
                                    cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            time.sleep(6)
            proc.send_signal(signal.SIGINT)
            text, _ = proc.communicate(timeout=120)
            saved = "saving what was crawled" in text
            print(f"[3] batch 1 interrupted with Ctrl+C, partial results saved: {'ok' if saved else 'FAILED'}")
            if not saved:
                failures.append("interrupt did not save partial results")
            if "JSON not written yet" not in text or (work / "json_out" / "batch_01.json").exists():
                failures.append("an interrupted run should not write the JSON file")
        out = run([*crawl, "--batch", "1", "--worker", "binh"], work)
        line = next((l for l in out.splitlines() if l.startswith("input:")), "")
        print(f"    rerun after interrupt: {line}")
        if sys.platform != "win32" and "already done: 0 " in line:
            failures.append("rerun after interrupt started from zero")
        run([*crawl, "--batch", "2", "--worker", "chi"], work)
        print("[4] batches 1 and 2 finished")

        raw = pl.scan_parquet(str(work / "crawl_out" / "**" / "*.parquet")).select("id", "status").collect()
        dup = raw.height - raw["id"].n_unique()
        print(f"[5] raw rows {raw.height}, duplicate ids across runs: {dup}")
        if dup:
            failures.append(f"{dup} ids were recorded twice")

        report = run([str(ROOT / "merge.py"), "--inputs", "crawl_out", "--out", "merged"], work)
        st = pl.read_parquet(work / "merged" / "status.parquet")
        docs = pl.read_parquet(work / "merged" / "docs.parquet")
        got = dict(zip(st["id"].to_list(), st["status"].to_list()))
        missing = set(expected) - set(got)
        wrong = {i: (got[i], sorted(e)) for i, e in expected.items() if i in got and got[i] not in e}
        print(f"[6] merged: {st.height} ids, {docs.height} docs, missing {len(missing)}, unexpected status {len(wrong)}")
        if missing:
            failures.append(f"{len(missing)} ids missing after merge")
        for i, (g, e) in list(wrong.items())[:10]:
            failures.append(f"id {i}: got {g}, expected {e} ({st.filter(pl.col('id') == i)['url'][0]})")

        jdir = work / "json_out"
        per_batch = [len(json.loads((jdir / f"batch_{b:02d}.json").read_text(encoding="utf-8")))
                     if (jdir / f"batch_{b:02d}.json").exists() else -1 for b in range(3)]
        export = [str(ROOT / "export_json.py")]
        run([*export, "--input", "crawl_out", "--name", "all", "--rows-per-file", "100"], work)
        parts = sorted(jdir.glob("all-*.json"))
        merged_rows = [r for p in parts for r in json.loads(p.read_text(encoding="utf-8"))]
        same = {r["id"]: r["status"] for r in merged_rows} == got and len(merged_rows) == len(got)
        run([*export, "--input", "crawl_out", "--name", "ok", "--jsonl", "--only-ok", "--with-html"], work)
        ok_lines = [json.loads(l) for l in (jdir / "ok.jsonl").read_text(encoding="utf-8").splitlines()]
        run([*export, "--input", "merged/docs.parquet"], work)
        docs_rows = json.loads((jdir / "docs.json").read_text(encoding="utf-8"))
        json_ok = (per_batch == [170, 170, len(got) - 340] and same and len(parts) == math.ceil(len(got) / 100)
                   and len(ok_lines) == docs.height and all("<" in r["html"] or not r["html"] for r in ok_lines)
                   and len(docs_rows) == docs.height)
        print(f"    JSON export: per batch {per_batch}, {len(parts)} parts of 100, jsonl ok rows {len(ok_lines)}, "
              f"docs.json {len(docs_rows)}: {'ok' if json_ok else 'FAILED'}")
        if not json_ok:
            failures.append("JSON export does not match the merged results")

        langs = dict(docs.group_by("lang").len().iter_rows())
        zh_docs = docs.filter(pl.col("url").str.contains("/zh/"))
        zh_ok = zh_docs.height > 0 and zh_docs["text"].str.contains("肾结石").all() and (zh_docs["lang"] == "zh").all()
        print(f"[7] languages {langs}, GBK page decoded: {'ok' if zh_ok else 'FAILED'}")
        if not zh_ok:
            failures.append("chinese GBK page was not decoded correctly")
        if not langs.get("vi") or not langs.get("en"):
            failures.append("vi/en language guess missing")
        noisy = docs.filter(pl.col("text").str.contains("tracking|Liên hệ"))
        if noisy.height:
            failures.append(f"{noisy.height} docs still contain menu/script text")
        old_zh = docs.filter(pl.col("url").str.contains("/yxbk/"))
        old_ok = old_zh.height == 20 and old_zh["text"].str.contains("男性健康的标准").all()
        garbled = docs.filter(pl.col("text").str.contains(r"[가-힯Ѐ-ӿ]")).height
        print(f"    old GBK pages without charset decoded: {'ok' if old_ok else 'FAILED'}, garbled docs: {garbled}")
        if not old_ok or garbled:
            failures.append("some Chinese pages were decoded with the wrong charset")
        messy = docs.filter(pl.col("text").str.contains(r"  |\n\n|^\s|\s$|\n\s|\s\n")).height
        if messy:
            failures.append(f"{messy} docs still contain repeated or leading/trailing whitespace")

        html_rows = pl.scan_parquet(str(work / "crawl_out" / "**" / "*.parquet")).filter(
            (pl.col("status") == "ok") & pl.col("html").is_not_null()).select(pl.len()).collect().item()
        print(f"[8] ok rows with stored html: {html_rows}")
        if not html_rows:
            failures.append("html was not stored")

        extractors = dict(docs.group_by("extractor").len().iter_rows())
        dated = docs.filter(pl.col("url").str.contains("/bai-viet/"))
        dates_ok = dated.height > 0 and (dated["published_at"] == "2024-03-05").all()
        hashes_ok = (docs["text_sha256"].str.len_chars() == 64).all()
        print(f"[8b] extractors {extractors}, published date: {'ok' if dates_ok else 'FAILED'}, "
              f"text hash: {'ok' if hashes_ok else 'FAILED'}")
        if "" in extractors or None in extractors or not dates_ok or not hashes_ok:
            failures.append("extractor, published_at or text_sha256 is missing in docs.parquet")

        groups = pl.read_parquet(work / "merged" / "duplicates.parquet")
        sizes = sorted(groups["size"].to_list(), reverse=True)
        pairs = groups.filter(pl.col("size") == 2)
        dup_ok = (sizes == [8] + [4] * 3 + [3] * 7 + [2] * 5 and (pairs["domains"].list.len() == 2).all()
                  and docs.filter(pl.col("dup_count") > 1).height == sum(sizes)
                  and docs.filter(pl.col("id") == pl.col("canonical_id")).height == docs.height - sum(sizes) + len(sizes)
                  and docs.filter(pl.col("url").str.contains("/dup/"))["text_sha256"].n_unique() == 10)
        print(f"[8c] duplicate content: {len(sizes)} groups, largest {sizes[:4]}: {'ok' if dup_ok else 'FAILED'}")
        if not dup_ok:
            failures.append("duplicate detection did not find the expected groups")

        sys.path.insert(0, str(ROOT))
        from extract import extract_document
        qa = ("<html><head><title>头顶掉头发_有问必答</title></head><body><div class='nav'>有问必答 内科 外科 儿科</div>"
              "<h1 id='d_askH1'>头顶掉头发</h1><div class='b_askab1'><span>男 | 28岁</span><span>2011-03-02 19:59:32</span></div>"
              "<div class='b_askcont' id='d_msCon'><p class='crazy_new'><span>健康咨询描述：</span> 头顶掉头发很多<br/>一直都是</p></div>"
              "<div class='b_answerbox'><div class='b_answerli'><span class='b_sp2'>擅长: 儿科的常见病</span>"
              "<div class='b_anscont_cont'><div class='crazy_new'><p>病情分析：<br/>肝肾两虚气血不足。<br/>指导意见：<br/>多吃蔬菜。</p></div>"
              "<div class='b_ansaddbox'><div class='b_ansaddli'><span class='b_ansaddti'>追问</span><p>需要吃药吗</p>"
              "<div class='img' style='display:none;'><var>附件：点击查看大图</var></div></div>"
              "<div class='b_ansaddli'><span class='b_docaddti'>医生回答：</span><p>可以先调整饮食</p></div></div></div></div>"
              "<div class='b_answerli zhenshiAD'></div></div><div class='gift'>赠送医生锦旗 请使用微信扫一扫</div></body></html>")
        r = extract_document(qa.encode(), "https://www.120ask.com/question/1.htm", "html", False)
        t = r["text"]
        rule_ok = (r["extractor"] == "site:120ask" and r["published_at"] == "2011-03-02" and t.startswith("头顶掉头发")
                   and all(x in t for x in ("头顶掉头发很多", "肝肾两虚气血不足。", "多吃蔬菜。", "追问：需要吃药吗", "医生回答：可以先调整饮食"))
                   and not any(x in t for x in ("锦旗", "擅长", "附件", "内科 外科")))
        other = extract_document(qa.encode(), "https://example.org/question/1.htm", "html", False)
        print(f"[8d] site rule for question-and-answer pages: {'ok' if rule_ok else 'FAILED'} "
              f"(other hosts use {other['extractor']})")
        if not rule_ok or other["extractor"].startswith("site:"):
            failures.append("the 120ask site rule did not extract the question and answers correctly")

        menu = "<nav>" + "".join(f"<a>Trang chủ {i}</a><a>Đặt lịch khám {i}</a>" for i in range(20)) + "</nav>"
        related = ("<h1>Tin tức cùng chuyên mục</h1>"
                   + "".join(f"<div class='post-item'><a>Bài khác số {i}</a><span>02/10/2026</span></div>" for i in range(4)))
        article = ("<html><head><title>Rối loạn thích ứng</title></head><body>" + menu + "<div id='content-post'>"
                   "<div id='title-print'><span>Ngày đăng: 14/01/2025</span></div><h3 class='h3'>Rối loạn thích ứng</h3>"
                   "<div class='post-detail__content'><div class='post-detail__content-item'><span>14/01/2025</span></div>"
                   "<div class='post-detail__content-item'><span>6054 lượt xem</span></div></div>"
                   "<div class='content-excerpt'><div>Đoạn mở đầu tóm tắt bài viết về rối loạn thích ứng.</div></div>"
                   "<div class='content-editor'><div><p>Người bệnh nhập viện\r\ntrong tình trạng khó ngủ.</p>"
                   "<ul><li>Số điện thoại: 0243</li></ul><table><tr><td>Triệu chứng</td><td>Lo âu kéo dài</td></tr></table>"
                   "</div></div></div>" + related + "</body></html>")
        r = extract_document(article.encode(), "https://bachmai.gov.vn/bai-viet/x?id=1", "html", False)
        t = r["text"]
        video = ("<html><body>" + menu + "<div id='content-post'><h3 class='h3'>Chia sẻ của bác sĩ</h3>"
                 "<div class='content-excerpt'></div><div class='content-editor'><div><iframe src='x'></iframe></div></div>"
                 "</div>" + related + "</body></html>")
        v = extract_document(video.encode(), "https://bachmai.gov.vn/bai-viet/y?id=2", "html", False)
        article_ok = (r["extractor"] == "site:bachmai" and r["published_at"] == "2025-01-14" and r["title"] == "Rối loạn thích ứng"
                      and t.startswith("Đoạn mở đầu tóm tắt") and "Người bệnh nhập viện trong tình trạng khó ngủ." in t
                      and all(x in t for x in ("Số điện thoại: 0243", "Lo âu kéo dài"))
                      and not any(x in t for x in ("Tin tức cùng chuyên mục", "Bài khác", "Trang chủ", "lượt xem"))
                      and v["text"] == "" and v["extractor"] == "site:bachmai")
        print(f"     site rule for bachmai.gov.vn articles (date, opening paragraph, no menu text): "
              f"{'ok' if article_ok else 'FAILED'}")
        if not article_ok:
            failures.append("the bachmai site rule did not extract the article, its date or its opening paragraph correctly")

        shards = sorted((work / "crawl_out" / "batch_00").glob("*.parquet"))
        old_cols = [c for c in pl.read_parquet_schema(shards[0]) if c not in ("extractor", "published_at", "text_sha256")]
        pl.read_parquet(shards[0]).select(old_cols).write_parquet(shards[0])
        run([str(ROOT / "merge.py"), "--inputs", "crawl_out", "--out", "merged_mixed"], work)
        run([*export, "--input", "crawl_out/batch_00", "--name", "mixed"], work)
        mixed_docs = pl.read_parquet(work / "merged_mixed" / "docs.parquet")
        mixed_json = json.loads((jdir / "mixed.json").read_text(encoding="utf-8"))
        out = run([*crawl, "--batch", "0", "--worker", "an"], work)
        rx = run([str(ROOT / "reextract.py"), "--input", "crawl_out/batch_00", "--workers", "2", "--min-chars", "20"], work)
        after = pl.read_parquet(shards[0])
        mixed_ok = (mixed_docs.height == docs.height and (mixed_docs["text_sha256"].str.len_chars() == 64).all()
                    and len(mixed_json) == 170 and "nothing to do" in out and "text changed: 0" in rx
                    and "extractor" in after.columns and after.filter(pl.col("status") == "ok")["extractor"].str.len_chars().min() > 0)
        print(f"[8e] files written by the previous version still work, re-extraction keeps the text: "
              f"{'ok' if mixed_ok else 'FAILED'}")
        if not mixed_ok:
            failures.append("old-format shards or re-extraction did not behave as expected")
            print(rx[-600:])

        retry = run([*crawl, "--batch", "2", "--worker", "chi", "--retry-failed"], work)
        line = next((l for l in retry.splitlines() if l.startswith("input:")), "")
        print(f"[9] retry run: {line}")
        if "to crawl now: 0" in line:
            failures.append("--retry-failed found nothing to retry")
    finally:
        stop()
        if args.keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

    print(f"\n{time.time() - t0:.0f}s")
    if failures:
        print("SELFTEST FAILED")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("SELFTEST PASSED")


if __name__ == "__main__":
    main()
