from __future__ import annotations

import hashlib
import os
import re
import sys
import unicodedata
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import tldextract

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

RETRYABLE = {
    "timeout", "conn_error", "dns_error", "ssl_error", "http_5xx", "rate_limited",
    "robots_unreachable", "domain_skipped", "error",
}

STATUS_RANK = {
    "ok": 0, "empty_text": 1, "extract_error": 2, "not_found": 3, "blocked": 4, "http_4xx": 5,
    "robots_disallowed": 6, "skipped_type": 7, "too_large": 8, "bad_url": 9, "http_other": 10,
}

_HOST_RE = r"^[A-Za-z][A-Za-z0-9+.\-]*://(?:[^@/?#]*@)?(\[[^\]]+\]|[^/?#:]+)(?::(\d+))?"

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_VI = re.compile(
    r"[ăâđêôơưàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹýỵ]",
    re.IGNORECASE,
)
_LATIN = re.compile(r"[A-Za-z]")


def utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def host_of(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    if port and port not in (80, 443):
        host = f"{host}:{port}"
    return host


@lru_cache(maxsize=1_000_000)
def domain_of_host(host: str) -> str:
    if not host:
        return ""
    name, _, port = host.partition(":")
    ext = _EXTRACT(name)
    top = getattr(ext, "top_domain_under_public_suffix", None)
    if top is None:
        top = ext.registered_domain
    if top:
        return top
    return host


def domain_of(url: str) -> str:
    return domain_of_host(host_of(url))


def guess_lang(text: str, sample: int = 4000) -> str:
    s = unicodedata.normalize("NFC", text[:sample])
    cjk = len(_CJK.findall(s))
    vi = len(_VI.findall(s))
    lat = len(_LATIN.findall(s))
    letters = cjk + vi + lat
    if letters < 20:
        return ""
    if cjk / letters > 0.3:
        return "zh"
    if vi / max(1, vi + lat) > 0.05:
        return "vi"
    if lat / letters > 0.6:
        return "en"
    return "other"


MAX_TEXT_CHARS = 2_000_000
MIN_SITE_CHARS = 20

SHARD_SCHEMA = pa.schema([
    ("id", pa.int64()),
    ("url", pa.string()),
    ("final_url", pa.string()),
    ("domain", pa.string()),
    ("status", pa.string()),
    ("http_status", pa.int32()),
    ("content_type", pa.string()),
    ("title", pa.string()),
    ("text", pa.string()),
    ("lang", pa.string()),
    ("n_chars", pa.int32()),
    ("html", pa.binary()),
    ("error", pa.string()),
    ("fetched_at", pa.string()),
    ("worker", pa.string()),
    ("batch", pa.int32()),
    ("extractor", pa.string()),
    ("published_at", pa.string()),
    ("text_sha256", pa.string()),
])


def write_shard(rows: list[dict], path: Path) -> None:
    table = pa.Table.from_pylist(rows, schema=SHARD_SCHEMA)
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path)


def sha256_text(text: str | None) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def text_status(text: str, extractor: str, min_chars: int) -> str:
    needed = MIN_SITE_CHARS if extractor.startswith("site:") else min_chars
    return "ok" if len(text) >= needed else "empty_text"


COLUMN_TYPES = {
    "id": pl.Int64, "http_status": pl.Int32, "n_chars": pl.Int32, "batch": pl.Int32, "html": pl.Binary,
    "canonical_id": pl.Int64, "dup_count": pl.Int32,
}


def find_files(inputs: list[str]) -> list[str]:
    files: list[str] = []
    for item in inputs:
        p = Path(item)
        if p.is_file() and p.suffix == ".parquet":
            files.append(str(p))
        elif p.is_dir():
            files.extend(str(f) for f in sorted(p.rglob("*.parquet")))
    return sorted(set(files))


def scan_light(files: list[str], columns: list[str], exprs: tuple = ()) -> pl.DataFrame:
    if not files:
        return pl.DataFrame(schema={c: pl.String for c in [*columns, "file"]})
    try:
        lf = pl.scan_parquet(files, include_file_paths="file", missing_columns="insert", extra_columns="ignore")
        return lf.select(*columns, *exprs, "file").collect()
    except Exception:
        pass
    frames = []
    needed = sorted(set(columns) | {name for e in exprs for name in e.meta.root_names()})
    for f in files:
        try:
            df = pl.read_parquet(f, columns=needed)
            frames.append(df.select(*columns, *exprs).with_columns(pl.lit(f).alias("file")))
        except Exception as exc:
            print(f"warning: skipping unreadable file {f}: {exc}")
    if not frames:
        return pl.DataFrame(schema={c: pl.String for c in [*columns, "file"]})
    return pl.concat(frames, how="vertical_relaxed")


def read_shard(file: str, columns: list[str]) -> pl.DataFrame:
    schema = pl.read_parquet_schema(file)
    df = pl.read_parquet(file, columns=[c for c in columns if c in schema])
    missing = [c for c in columns if c not in schema]
    if missing:
        df = df.with_columns([pl.lit(None, dtype=COLUMN_TYPES.get(c, pl.String)).alias(c) for c in missing])
    return df.select(columns)


def pick_winners(light: pl.DataFrame) -> pl.DataFrame:
    return (
        light.with_columns(pl.col("status").replace_strict(STATUS_RANK, default=50, return_dtype=pl.Int32).alias("rank"))
        .sort(["id", "rank", "fetched_at"], descending=[False, False, True])
        .unique("id", keep="first", maintain_order=True)
    )
