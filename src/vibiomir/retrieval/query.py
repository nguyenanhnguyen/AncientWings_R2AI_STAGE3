"""C1: load the query set and build the text variants each channel searches with.

Queries are patient-style Vietnamese questions: short, often several facts in one sentence. The
original wording is always kept as the primary variant, because an encoder trained on natural
language loses signal when the question is reduced to keywords. The `keyword` variant only drops
politeness and framing phrases and exists for BM25, where those tokens add nothing.

Translating the query into Chinese or English would let BM25 reach the Chinese half of the corpus.
That needs a translation model that satisfies the rules, so it is left as an explicit hook:
`--translations` reads a prepared file instead of inventing text at run time.
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
    """Map of variant name -> text. `original` is always present and always first."""
    result = {'original': query['query']}
    if use_keyword:
        keyword = strip_filler(query['query'])
        if keyword != query['query']:
            result['keyword'] = keyword
    for language, table in (translations or {}).items():
        text = table.get(query['id'])
        if text:
            result[f'translated_{language}'] = normalise_source(text)
    return result


def load_translations(path):
    """Prepared translations: JSONL rows of {"id": int, "lang": "zh"|"en", "text": str}."""
    table = {}
    for row in storage.read_jsonl(path):
        table.setdefault(row['lang'], {})[int(row['id'])] = row['text']
    return table
