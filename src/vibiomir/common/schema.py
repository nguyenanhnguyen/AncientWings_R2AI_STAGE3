"""Record formats passed between blocks, plus the text normalisation both D and E rely on.

One document id is the integer `id` from links_corpus.parquet. Every later stage carries that
integer unchanged: the contest only counts documents from that list, so a renumbered id is a
wasted prediction. Chunk ids are derived (`<doc_id>:<order>`) and never leave the pipeline.
"""
import html
import re
import unicodedata

import pyarrow as pa

# Block A output consumed by A4 (scripts/chunk.py). Written by the crawler's export step.
DOCUMENT_FIELDS = ('id', 'url', 'final_url', 'title', 'text', 'domain', 'extractor',
                   'published_at', 'raw_path', 'raw_sha256', 'text_sha256', 'duplicate_doc_ids')

# A4 output. char_start/char_end index into the document text so D2 can re-slice the exact
# source span instead of trusting a copy of it.
CHUNK_SCHEMA = pa.schema([
    ('chunk_id', pa.string()),
    ('doc_id', pa.int64()),
    ('chunk_order', pa.int32()),
    ('char_start', pa.int32()),
    ('char_end', pa.int32()),
    ('text', pa.string()),
    ('title', pa.string()),
    ('lang', pa.string()),
    ('n_tokens', pa.int32()),
    ('domain', pa.string()),
])


def chunk_id(doc_id, order):
    return f'{doc_id}:{order}'


# --- Text normalisation ---

_WHITESPACE = re.compile(r'\s+')


def normalise_source(text):
    """Light normalisation for stored text: NFC, LF line endings, no trailing blanks.

    Keeps case, Vietnamese diacritics, numbers, units and paragraph breaks. The corpus must stay
    faithful to the source because submitted chunk_text has to be a real span of it.
    """
    if not text:
        return ''
    text = unicodedata.normalize('NFC', text).replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[ \t ]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def normalise_for_match(text):
    """The evaluator's comparison form: NFKC, HTML entities decoded, lowercase, spaces collapsed.

    Used only when comparing texts (metrics, duplicate detection). Never stored as corpus text.
    """
    if not text:
        return ''
    text = unicodedata.normalize('NFKC', text)
    text = html.unescape(text)
    return _WHITESPACE.sub(' ', text.lower()).strip()


# A CJK character is its own token; Latin/digit runs are tokens. The official LCS token basis is
# not published, so this is our stated assumption and both metrics and chunk sizing use it.
_TOKEN_RE = re.compile(r'[㐀-鿿぀-ヿ가-힯]|[^\W\d_]+|\d+', re.UNICODE)


def tokenize_for_match(text):
    return _TOKEN_RE.findall(normalise_for_match(text))


def count_tokens(text):
    return len(_TOKEN_RE.findall(text or ''))


_VI_DIACRITICS = re.compile(r'[ăâđêôơưĂÂĐÊÔƠƯàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệ'
                            r'ìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]')
_CJK = re.compile(r'[㐀-鿿]')


def detect_language(text):
    """Script-based hint, not a calibrated classifier. `en` here means 'Latin, not Vietnamese'."""
    if not text:
        return 'unknown'
    sample = text[:4000]
    if len(_CJK.findall(sample)) / max(1, len(sample)) > 0.1:
        return 'zh'
    letters = sum(ch.isalpha() for ch in sample)
    if letters < 20:
        return 'unknown'
    if len(_VI_DIACRITICS.findall(sample)) / max(1, letters) > 0.01:
        return 'vi'
    return 'en'


# --- Block D output: the submission file itself ---

def submission_row(query_id, doc_ids, chunks, doc_id_as_string=False):
    """One entry of the submission array. Empty lists are required, not optional."""
    cast = str if doc_id_as_string else int
    return {
        'id': int(query_id),
        'relevant_docs': [cast(value) for value in doc_ids],
        'relevant_chunks': [{'doc_id': cast(item['doc_id']),
                             'chunk_text': item['chunk_text'],
                             'chunk_order': int(item['chunk_order'])} for item in chunks],
    }


def validate_submission_shape(rows, expected_query_ids):
    """Structural check only; validate.py also proves every chunk is a real source span."""
    problems = []
    seen = []
    for position, row in enumerate(rows):
        where = f'row {position}'
        if not isinstance(row, dict) or 'id' not in row:
            problems.append(f'{where}: missing id')
            continue
        if not isinstance(row['id'], int) or isinstance(row['id'], bool):
            problems.append(f'{where}: id must be an integer')
            continue
        seen.append(row['id'])
        for key in ('relevant_docs', 'relevant_chunks'):
            if not isinstance(row.get(key), list):
                problems.append(f"query {row['id']}: {key} must be a list")
        for item in row.get('relevant_chunks') or []:
            if not isinstance(item, dict) or 'doc_id' not in item or 'chunk_text' not in item:
                problems.append(f"query {row['id']}: chunk needs doc_id and chunk_text")
                continue
            if not isinstance(item['chunk_text'], str) or not item['chunk_text'].strip():
                problems.append(f"query {row['id']}: empty chunk_text")
            if 'chunk_order' in item and (not isinstance(item['chunk_order'], int)
                                          or isinstance(item['chunk_order'], bool)
                                          or item['chunk_order'] < 0):
                problems.append(f"query {row['id']}: chunk_order must be a non-negative integer")
    duplicates = sorted({value for value in seen if seen.count(value) > 1})
    if duplicates:
        problems.append(f'duplicate query ids: {duplicates[:10]}')
    missing = sorted(set(expected_query_ids) - set(seen))
    if missing:
        problems.append(f'missing {len(missing)} query ids, first: {missing[:10]}')
    extra = sorted(set(seen) - set(expected_query_ids))
    if extra:
        problems.append(f'unknown query ids: {extra[:10]}')
    return problems
