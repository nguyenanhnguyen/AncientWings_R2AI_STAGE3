"""C1: load the query set and build the text variants each channel searches with.

Queries are patient-style Vietnamese questions: short, often several facts in one sentence. The
original wording is always kept as the primary variant, because an encoder trained on natural
language loses signal when the question is reduced to keywords. The `keyword` variant only drops
politeness and framing phrases and exists for BM25, where those tokens add nothing.

Translations into Chinese/English and HyDE passages come from `translate.py` (an open local LLM)
and are read from its prepared file through `--translations`; retrieval never generates text.
They let BM25 and the reranker work within the language of the Chinese majority of the corpus.
"""
import re

from ..common import storage
from ..common.schema import normalise_source

# Framing phrases, not medical content. Matched on the lowercase form, longest first.
_FILLER = [
    'cho em hỏi', 'cho tôi hỏi', 'xin bác sĩ cho biết', 'bác sĩ cho em hỏi', 'bác sĩ ơi',
    'em xin cảm ơn', 'xin cảm ơn', 'em cảm ơn', 'cảm ơn bác sĩ', 'mong bác sĩ tư vấn',
    'nhờ bác sĩ tư vấn', 'xin chào bác sĩ', 'em chào bác sĩ', 'chào bác sĩ', 'thưa bác sĩ',
]
_TRAILING = re.compile(r'\b(ạ|vậy ạ|thế ạ|nhé|nha|với ạ)\b', re.IGNORECASE)


def load_queries(path):
    """Return [{'id': int, 'query': str}] sorted by id, from query.parquet or a JSONL file."""
    path = str(path)
    rows = storage.read_parquet(path) if path.endswith('.parquet') else storage.read_jsonl(path)
    out = []
    for row in rows:
        text = normalise_source(row.get('query') or '')
        if not text:
            raise ValueError(f"Query {row.get('id')} is empty; the submission needs every query.")
        out.append({'id': int(row['id']), 'query': text})
    identifiers = [row['id'] for row in out]
    if not identifiers:
        raise ValueError('The query file is empty.')
    if len(set(identifiers)) != len(identifiers):
        raise ValueError('Duplicate query ids in the query file.')
    return sorted(out, key=lambda row: row['id'])


def strip_filler(text):
    lowered = text
    for phrase in sorted(_FILLER, key=len, reverse=True):
        lowered = re.sub(re.escape(phrase), ' ', lowered, flags=re.IGNORECASE)
    lowered = _TRAILING.sub(' ', lowered)
    return re.sub(r'\s+', ' ', lowered).strip() or text


def variants(query, use_keyword=False, translations=None):
    """Map of variant name -> text. `original` is always present and always first.

    `translations` maps a variant name (translated_zh, hyde_vi, ...) to {query id: text}.
    """
    result = {'original': query['query']}
    if use_keyword:
        keyword = strip_filler(query['query'])
        if keyword != query['query']:
            result['keyword'] = keyword
    for name, table in (translations or {}).items():
        text = table.get(query['id'])
        if text:
            result[name] = normalise_source(text)
    return result


def variant_language(name):
    """Language of a variant's text: 'translated_zh' -> 'zh', 'original' -> 'vi'."""
    if name.startswith(('translated_', 'hyde_')):
        return name.rsplit('_', 1)[1]
    return 'vi'


def load_translations(path, queries=None):
    """Prepared query-side text: JSONL rows {"id", "lang", "text", "kind"?}.

    kind "translate" (the default, as in older files) gives variant translated_<lang>; kind "hyde"
    gives hyde_<lang>. Returns {variant name: {query id: text}}.
    """
    table = {}
    originals = {row['id']: row['query'] for row in (queries or [])}
    for row in storage.read_jsonl(path):
        kind = row.get('kind') or 'translate'
        allowed = ('en', 'zh') if kind == 'translate' else ('en', 'zh', 'vi')
        if kind not in ('translate', 'hyde') or row['lang'] not in allowed or not row['text'].strip():
            raise ValueError('Translation must have kind translate (en/zh) or hyde (en/zh/vi) '
                             'and nonempty text.')
        if row.get('query_sha256') and originals:
            if int(row['id']) not in originals or storage.sha256_text(
                    originals[int(row['id'])]) != row['query_sha256']:
                raise ValueError('Translation cache belongs to different query text.')
        name = f"translated_{row['lang']}" if kind == 'translate' else f"hyde_{row['lang']}"
        if int(row['id']) in table.get(name, {}):
            raise ValueError('Duplicate translation id/language.')
        table.setdefault(name, {})[int(row['id'])] = row['text']
    return table
