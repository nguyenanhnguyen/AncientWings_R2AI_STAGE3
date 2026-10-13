"""Read-only corpus audit helpers embedded in review_hf_data_quality.ipynb."""
from pathlib import Path
from collections import Counter
import hashlib
import html
import json
import re
import sqlite3
import unicodedata
from urllib.parse import urlsplit

TEXT_KEYS = ('text', 'content', 'body', 'question', 'query', 'q', 'answers', 'answer', 'replies')
TOKEN_RE = re.compile(r'[㐀-鿿]|[^\W\d_]+|\d+', re.UNICODE)
CJK_RE = re.compile(r'[㐀-鿿]')
VI_RE = re.compile(r'[ăâđêôơưĂÂĐÊÔƠƯàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]')
HTML_RE = re.compile(r'</?(?:html|body|div|p|span|br|a|script|style|table|li|h[1-6])\b', re.I)
MOJI_RE = re.compile(r'Ã[\x80-\xbf]|Ä[\x80-\xbf]|Æ[\x80-\xbf]|á[»º]|â€|ï¿½')
BLOCK_RE = re.compile(r'access denied|verify (?:that )?you are human|checking your browser|'
                      r'just a moment|captcha|page not found|404 not found|403 forbidden|'
                      r'không tìm thấy trang|truy cập bị từ chối|页面不存在|访问被拒绝', re.I)
BOILER_RE = re.compile(r'cookie|privacy policy|terms of (?:use|service)|all rights reserved|'
                      r'đăng nhập|đăng ký|chính sách bảo mật|bản quyền|bài viết liên quan|'
                      r'联系我们|免责声明|版权所有|相关阅读', re.I)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n',
                          encoding='utf-8')


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def as_str(value):
    return value if isinstance(value, str) else ''


def norm_match(value):
    return re.sub(r'\s+', ' ', html.unescape(unicodedata.normalize('NFKC', value)).lower()).strip()


def to_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 2**63 - 1 else None
    if isinstance(value, str) and re.fullmatch(r'\d+', value.strip()):
        parsed = int(value)
        return parsed if parsed <= 2**63 - 1 else None
    return None


def join_parts(value):
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [part for item in value for part in join_parts(item)]
    if isinstance(value, dict):
        return join_parts(value.get('text') or value.get('content') or value.get('answer'))
    return []


def text_of(row):
    for key in ('text', 'content', 'body'):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    parts = []
    for keys in [('question', 'query', 'q'), ('answers', 'answer', 'replies')]:
        for key in keys:
            values = join_parts(row.get(key))
            if values:
                parts.extend(values)
                break
    return '\n\n'.join(parts)


def url_info(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname:
            return None, ''
        return parsed, parsed.hostname.lower()
    except ValueError:
        return None, ''


def script_hint(text):
    sample = text[:4000]
    letters = sum(c.isalpha() for c in sample)
    if letters < 20:
        return 'unknown'
    if len(CJK_RE.findall(sample)) / max(1, len(sample)) > 0.10:
        return 'cjk'
    if len(VI_RE.findall(sample)) / letters > 0.01:
        return 'vi_hint'
    return 'latin_other'


def feature(row, file_name, row_no, cfg):
    text = text_of(row)
    normalized = norm_match(text)
    doc_id = to_id(row.get('id'))
    url = as_str(row.get('url'))
    final_url = as_str(row.get('final_url')) or url
    source_parsed, source_domain = url_info(url)
    final_parsed, final_domain = url_info(final_url)
    domain = final_domain or source_domain or as_str(row.get('domain')) or '(missing)'
    title = as_str(row.get('title')).strip()
    status = as_str(row.get('status'))
    quality = as_str(row.get('quality_status'))
    declared_lang = as_str(row.get('lang') or row.get('language_hint'))
    raw_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
    normalized_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest() if normalized else None
    stored_hash = as_str(row.get('text_sha256'))
    hard, review = [], []
    if doc_id is None:
        hard.append('invalid_id')
    if not source_parsed:
        hard.append('invalid_url')
    if not normalized:
        hard.append('empty_text')
    if row.get('text') is not None and not isinstance(row['text'], str):
        hard.append('non_string_text')
    # Stored hash/count only have definite semantics for the original text field.
    if isinstance(row.get('text'), str):
        if stored_hash and stored_hash.lower() != hashlib.sha256(row['text'].encode('utf-8')).hexdigest():
            hard.append('text_sha256_mismatch')
        if row.get('char_count') is not None and row['char_count'] != len(row['text']):
            hard.append('char_count_mismatch')
    if status and status not in {'extracted', 'ok'}:
        hard.append('failed_status_in_corpus')
    if quality == 'rejected':
        hard.append('rejected_in_corpus')
    if source_parsed and final_parsed and source_parsed.path not in ('', '/') and \
            final_parsed.path in ('', '/') and not final_parsed.query:
        review.append('homepage_redirect')
    if not final_parsed:
        review.append('invalid_final_url')
    if normalized and len(text) < cfg['min_chars']:
        review.append('short_text')
    if len(text) > cfg['long_chars']:
        review.append('very_long_text')
    if not title:
        review.append('missing_title')
    if title and normalized == norm_match(title):
        review.append('title_only')
    html_count = len(HTML_RE.findall(text))
    moji_count = len(MOJI_RE.findall(text))
    replacement_count = text.count('\ufffd')
    if html_count:
        review.append('html_leftover')
    if moji_count or replacement_count:
        review.append('encoding_suspect')
    if BLOCK_RE.search(title) or (len(text) < 1500 and BLOCK_RE.search(text)):
        review.append('block_or_error_page_suspect')
    lines = [norm_match(line) for line in text.splitlines() if len(line.strip()) >= 15]
    repeated_chars = sum(len(line) * (count - 1) for line, count in Counter(lines).items() if count > 1)
    repeated_ratio = repeated_chars / max(1, len(text))
    if len(lines) >= 5 and repeated_ratio > 0.35:
        review.append('repeated_lines')
    boiler_count = len(BOILER_RE.findall(text))
    if boiler_count >= 4 and len(text) < 2500:
        review.append('boilerplate_suspect')
    hint = script_hint(text)
    expected = {'zh': 'cjk', 'zh_hint': 'cjk', 'vi': 'vi_hint', 'vi_hint': 'vi_hint', 'en': 'latin_other'}
    if declared_lang in expected and hint != 'unknown' and expected[declared_lang] != hint:
        review.append('language_metadata_suspect')
    raw_flags = row.get('quality_flags')
    crawler_flags = raw_flags if isinstance(raw_flags, (list, tuple)) else ([raw_flags] if raw_flags else [])
    sample_key = hashlib.blake2b(f"{cfg['seed']}:{file_name}:{row_no}".encode(), digest_size=8).hexdigest()
    return {
        'file_name': file_name, 'row_no': row_no, 'id': doc_id, 'url': url, 'final_url': final_url,
        'domain': domain, 'title': title, 'declared_lang': declared_lang, 'script_hint': hint,
        'status': status, 'quality_status': quality, 'chars': len(text),
        'approx_tokens': len(TOKEN_RE.findall(text)), 'raw_hash': raw_hash,
        'norm_hash': normalized_hash, 'html_count': html_count, 'mojibake_count': moji_count,
        'replacement_count': replacement_count, 'repeat_ratio': repeated_ratio,
        'boiler_count': boiler_count, 'hard_flags': '|'.join(hard), 'review_flags': '|'.join(review),
        'crawler_flags': '|'.join(map(str, crawler_flags)), 'n_hard': len(hard), 'n_review': len(review),
        'preview': text[:500], 'tail': text[-200:], 'sample_key': sample_key,
    }


def scan_corpus(db, names, get_corpus, cfg):
    import pyarrow.parquet as pq
    columns = list(feature({}, '', 0, cfg))
    integer_columns = {'row_no', 'id', 'chars', 'approx_tokens', 'html_count', 'mojibake_count',
                       'replacement_count', 'boiler_count', 'n_hard', 'n_review'}
    definition = ', '.join(f'"{name}" ' + ('INTEGER' if name in integer_columns else
                                        'REAL' if name == 'repeat_ratio' else 'TEXT') for name in columns)
    db.execute('DROP TABLE IF EXISTS features')
    db.execute(f'CREATE TABLE features ({definition})')
    insert_sql = 'INSERT INTO features VALUES (' + ','.join('?' for _ in columns) + ')'
    inventory, file_lookup = [], {}
    for file_no, name in enumerate(names, 1):
        local = Path(get_corpus(name))
        file_lookup[name] = local
        parquet = pq.ParquetFile(local)
        schema_names = set(parquet.schema_arrow.names)
        needed = schema_names & (set(TEXT_KEYS) | {'id', 'url', 'final_url', 'domain', 'title', 'lang',
            'language_hint', 'status', 'quality_status', 'quality_flags', 'text_sha256', 'char_count'})
        row_no = 0
        for batch in parquet.iter_batches(batch_size=cfg['batch_size'], columns=sorted(needed)):
            rows = batch.to_pylist()
            if cfg['max_rows_per_file'] is not None:
                rows = rows[:max(0, cfg['max_rows_per_file'] - row_no)]
            values = []
            for row in rows:
                data = feature(row, name, row_no, cfg)
                values.append(tuple(data[key] for key in columns))
                row_no += 1
            db.executemany(insert_sql, values)
            if cfg['max_rows_per_file'] is not None and row_no >= cfg['max_rows_per_file']:
                break
        db.commit()
        inventory.append({'file_name': name, 'bytes': local.stat().st_size,
            'sha256': file_sha256(local), 'rows_available': parquet.metadata.num_rows,
            'rows_scanned': row_no, 'schema': str(parquet.schema_arrow),
            'missing_core_fields': '|'.join(sorted({'id', 'url', 'text'} - schema_names))})
        parquet.close()
        print(f'[{file_no}/{len(names)}] {name}: {row_no:,}/{parquet.metadata.num_rows:,} rows', flush=True)
    for key in ['id', 'norm_hash', 'domain', 'sample_key']:
        db.execute(f'CREATE INDEX IF NOT EXISTS ix_{key} ON features ("{key}")')
    db.commit()
    return inventory, file_lookup


def table(db, query, params=()):
    import pandas as pd
    return pd.read_sql_query(query, db, params=params)


def quality_tables(db):
    import pandas as pd
    flags, crawler = Counter(), Counter()
    for hard, review, crawl in db.execute('SELECT hard_flags, review_flags, crawler_flags FROM features'):
        flags.update(set(x for x in (hard + '|' + review).split('|') if x))
        crawler.update(set(x for x in crawl.split('|') if x))
    n = db.execute('SELECT COUNT(*) FROM features').fetchone()[0]
    result = {
        'quality_flags': pd.DataFrame([{'flag': k, 'rows': v, 'row_share': v / max(1, n)}
            for k, v in flags.most_common()], columns=['flag', 'rows', 'row_share']),
        'crawler_flags': pd.DataFrame(crawler.most_common(), columns=['flag', 'rows']),
        'duplicate_ids': table(db, """
            SELECT id, COUNT(*) AS rows, COUNT(DISTINCT raw_hash) AS text_versions,
                   COUNT(DISTINCT url) AS url_versions, MIN(file_name) AS example_file
            FROM features WHERE id IS NOT NULL GROUP BY id HAVING COUNT(*) > 1
            ORDER BY text_versions DESC, rows DESC"""),
        'duplicate_text_groups': table(db, """
            SELECT norm_hash, COUNT(*) AS rows, COUNT(DISTINCT id) AS document_ids,
                   MIN(chars) AS min_chars, MIN(id) AS example_id, MIN(preview) AS preview
            FROM features WHERE norm_hash IS NOT NULL GROUP BY norm_hash HAVING COUNT(*) > 1
            ORDER BY document_ids DESC, rows DESC"""),
    }
    for key in ['domain', 'file_name', 'script_hint']:
        name = {'domain': 'by_domain', 'file_name': 'by_shard', 'script_hint': 'by_language'}[key]
        result[name] = table(db, f"""
            SELECT {key}, COUNT(*) AS rows, COUNT(DISTINCT id) AS unique_ids,
                   AVG(chars) AS mean_chars, AVG(n_hard > 0) AS hard_flag_share,
                   AVG(n_review > 0) AS review_flag_share
            FROM features GROUP BY {key} ORDER BY rows DESC""")
    result['language_metadata'] = table(db, """
        SELECT script_hint, declared_lang, COUNT(*) AS rows FROM features
        GROUP BY script_hint, declared_lang ORDER BY rows DESC""")
    return result


def source_coverage(db, links_path, batch_size=8192):
    import pyarrow.parquet as pq
    import pandas as pd
    db.executescript("""
        DROP TABLE IF EXISTS source_links;
        DROP TABLE IF EXISTS source_batch;
        CREATE TABLE source_links (id INTEGER PRIMARY KEY, source_url TEXT, source_domain TEXT);
        CREATE TEMP TABLE source_batch (id INTEGER, source_url TEXT, source_domain TEXT);
    """)
    domain_counts, n = Counter(), 0
    for batch_no, batch in enumerate(pq.ParquetFile(links_path).iter_batches(
            batch_size=batch_size, columns=['id', 'url']), 1):
        rows = []
        for row in batch.to_pylist():
            url = as_str(row.get('url'))
            domain = url_info(url)[1] or '(missing)'
            domain_counts[domain] += 1
            rows.append((to_id(row.get('id')), url, domain))
        n += len(rows)
        db.execute('DELETE FROM source_batch')
        db.executemany('INSERT INTO source_batch VALUES (?,?,?)', rows)
        db.execute("""INSERT OR IGNORE INTO source_links
            SELECT b.id, b.source_url, b.source_domain FROM source_batch b
            WHERE b.id IS NOT NULL AND EXISTS (SELECT 1 FROM features f WHERE f.id=b.id)""")
        if batch_no % 50 == 0:
            db.commit()
            print(f'Đối chiếu {n:,} link nguồn', flush=True)
    db.commit()
    matched = db.execute('SELECT COUNT(*) FROM source_links').fetchone()[0]
    unknown = table(db, """
        SELECT DISTINCT f.id, f.url, f.file_name FROM features f
        LEFT JOIN source_links s ON f.id=s.id WHERE f.id IS NOT NULL AND s.id IS NULL""")
    mismatches = table(db, """
        SELECT f.id, f.url, s.source_url, f.file_name FROM features f JOIN source_links s ON f.id=s.id
        WHERE f.url != s.source_url""")
    coverage = pd.DataFrame(domain_counts.items(), columns=['source_domain', 'source_links'])
    covered = table(db, "SELECT source_domain, COUNT(*) AS corpus_ids FROM source_links GROUP BY source_domain")
    coverage = coverage.merge(covered, on='source_domain', how='left').fillna({'corpus_ids': 0})
    coverage['corpus_ids'] = coverage['corpus_ids'].astype(int)
    coverage['link_coverage'] = coverage['corpus_ids'] / coverage['source_links']
    return {'source_coverage_by_domain': coverage.sort_values('source_links', ascending=False),
            'ids_not_in_source': unknown, 'source_url_mismatches': mismatches}, {
                'source_rows': n, 'matched_ids': matched, 'link_coverage': matched / max(1, n),
                'unknown_ids': int(unknown['id'].nunique()), 'url_mismatch_rows': len(mismatches)}


def load_selected(selection, file_lookup, batch_size=1024, char_cap=None):
    import pyarrow.parquet as pq
    loaded = {}
    for name, group in selection.groupby('file_name'):
        targets = set(int(x) for x in group['row_no'])
        parquet = pq.ParquetFile(file_lookup[name])
        columns = sorted(set(parquet.schema_arrow.names) & set(TEXT_KEYS))
        offset = 0
        for rg in range(parquet.num_row_groups):
            size = parquet.metadata.row_group(rg).num_rows
            wanted = {i for i in targets if offset <= i < offset + size}
            if wanted:
                current = offset
                for batch in parquet.iter_batches(batch_size=batch_size, row_groups=[rg], columns=columns):
                    for row in batch.to_pylist():
                        if current in wanted:
                            text = text_of(row)
                            loaded[(name, current)] = text if char_cap is None else text[:char_cap]
                        current += 1
            offset += size
        parquet.close()
    result = selection.copy()
    result['text_sample'] = [loaded[(name, int(number))]
        for name, number in zip(result['file_name'], result['row_no'])]
    # Object dtype keeps .str available even for an empty selection.
    result['text_sample'] = result['text_sample'].astype('object')
    result['sample_truncated'] = result['text_sample'].str.len() < result['chars']
    return result


def make_samples(db, file_lookup, cfg):
    import pandas as pd
    sample_meta = table(db, 'SELECT * FROM features ORDER BY sample_key LIMIT ?', (cfg['sample_size'],))
    sample = load_selected(sample_meta, file_lookup, cfg['batch_size'], cfg['sample_char_cap'])
    random_review = table(db, """
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY domain, script_hint ORDER BY sample_key) AS rn
            FROM features) WHERE rn <= ? ORDER BY rn, sample_key LIMIT ?""",
        (cfg['manual_per_stratum'], cfg['manual_random_cap'])).drop(columns='rn')
    suspects = table(db, """
        SELECT f.* FROM features f WHERE n_hard>0 OR n_review>0
          OR id IN (SELECT id FROM features WHERE id IS NOT NULL GROUP BY id HAVING COUNT(*)>1)
          OR norm_hash IN (SELECT norm_hash FROM features WHERE norm_hash IS NOT NULL
                          GROUP BY norm_hash HAVING COUNT(DISTINCT id)>1)
        ORDER BY n_hard DESC, n_review DESC, sample_key LIMIT ?""", (cfg['manual_suspect_cap'],))
    random_review['sample_reason'] = 'domain_script_sample'
    suspects['sample_reason'] = 'suspect_or_duplicate'
    review_meta = pd.concat([suspects, random_review]).drop_duplicates(['file_name', 'row_no'])
    manual = load_selected(review_meta, file_lookup, cfg['batch_size'], cfg['sample_char_cap'])
    for column in ['usable', 'extraction_ok', 'medical_relevance', 'duplicate_template', 'review_notes']:
        manual[column] = ''
    return sample_meta, sample, manual


def near_duplicates(sample, threshold, seed, max_pairs=10000):
    import pandas as pd
    from datasketch import MinHash, MinHashLSH
    lsh = MinHashLSH(threshold=threshold, num_perm=64)
    hashes, pairs = {}, []
    pair_cap_hit = False
    for index, row in sample.iterrows():
        text = norm_match(row['text_sample'])
        if len(text) < 100:
            continue
        grams = {text[i:i+5] for i in range(len(text)-4)}
        signature = MinHash(num_perm=64, seed=seed)
        signature.update_batch([gram.encode('utf-8') for gram in sorted(grams)])
        for prior in sorted(lsh.query(signature), key=int):
            if hashes[prior] == row['norm_hash']:
                continue
            # Keep sketches rather than all shingle sets (large for multilingual text).
            other = sample.loc[int(prior)]
            prior_text = norm_match(other['text_sample'])
            prior_grams = {prior_text[i:i+5] for i in range(len(prior_text)-4)}
            overlap = len(grams & prior_grams) / max(1, len(grams | prior_grams))
            if overlap >= threshold:
                pairs.append({'id_a': other['id'], 'id_b': row['id'],
                    'file_a': other['file_name'], 'row_a': int(other['row_no']),
                    'file_b': row['file_name'], 'row_b': int(row['row_no']), 'jaccard': overlap,
                    'sample_truncated': bool(other['sample_truncated'] or row['sample_truncated']),
                    'preview_a': other['preview'], 'preview_b': row['preview']})
                if len(pairs) >= max_pairs:
                    pair_cap_hit = True
                    break
        if pair_cap_hit:
            break
        key = str(index)
        lsh.insert(key, signature)
        hashes[key] = row['norm_hash']
    return pd.DataFrame(pairs, columns=['id_a', 'id_b', 'file_a', 'row_a', 'file_b', 'row_b',
        'jaccard', 'sample_truncated', 'preview_a', 'preview_b']), pair_cap_hit


def query_probe(queries, sample):
    import numpy as np
    import pandas as pd
    from sklearn.feature_extraction.text import TfidfVectorizer
    candidates = sample.loc[sample['norm_hash'].notna()].drop_duplicates('norm_hash').reset_index(drop=True)
    texts = [norm_match(as_str(title) + '\n' + as_str(text))
             for title, text in zip(candidates['title'], candidates['text_sample'])]
    results = []
    if len(candidates) and len(queries) and any(len(text) >= 3 for text in texts):
        vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(3, 5), max_features=60000,
                                    min_df=1, sublinear_tf=True, dtype=np.float32)
        doc_vectors = vectorizer.fit_transform(texts)
        query_vectors = vectorizer.transform(queries['query'].map(norm_match))
        for start in range(0, len(queries), 32):
            scores = (query_vectors[start:start+32] @ doc_vectors.T).toarray()
            for offset, score_row in enumerate(scores):
                query = queries.iloc[start+offset]
                for rank, doc_index in enumerate(np.argsort(-score_row, kind='stable')[:3], 1):
                    document = candidates.iloc[int(doc_index)]
                    results.append({'query_id': query['id'], 'query': query['query'], 'rank': rank,
                        'tfidf_cosine': float(score_row[doc_index]), 'doc_id': document['id'],
                        'domain': document['domain'], 'script_hint': document['script_hint'],
                        'sample_truncated': bool(document['sample_truncated']),
                        'preview': document['preview'], 'url': document['url'],
                        'human_relevant': '', 'review_notes': ''})
    return pd.DataFrame(results, columns=['query_id', 'query', 'rank', 'tfidf_cosine', 'doc_id',
        'domain', 'script_hint', 'sample_truncated', 'preview', 'url', 'human_relevant', 'review_notes'])


def prepare_source_files(read_remote, repo, revision, links_hash, query_hash,
                         local_dir=None, query_fallback_revision=None):
    """References are optional; only verified bytes may reach ID/URL comparisons."""
    results, paths = {}, {}
    for key, filename, expected in [
        ('links', 'links_corpus.parquet', links_hash), ('queries', 'query.parquet', query_hash)
    ]:
        attempts = []
        candidates = [(revision, filename)]
        # The replacement snapshot has identical query bytes, unlike its links.
        if key == 'queries' and query_fallback_revision:
            candidates.append((query_fallback_revision, filename))
        if local_dir:
            candidates = [('local', filename)]
        chosen = None
        for candidate_revision, candidate_file in candidates:
            try:
                path = (Path(local_dir) / candidate_file if local_dir else
                        Path(read_remote(repo, candidate_file, candidate_revision)))
                actual = file_sha256(path)
                if actual != expected:
                    attempts.append({'revision': candidate_revision, 'filename': candidate_file,
                                     'error': 'sha256_mismatch', 'actual_sha256': actual})
                    continue
                chosen = path
                results[key] = {'status': 'ready', 'revision': candidate_revision,
                    'filename': candidate_file, 'sha256': actual, 'attempts': attempts}
                break
            except Exception as error:
                attempts.append({'revision': candidate_revision, 'filename': candidate_file,
                    'error': type(error).__name__,
                    'http_status': getattr(getattr(error, 'response', None), 'status_code', None)})
        paths[key] = chosen
        if chosen is None:
            results[key] = {'status': 'unavailable', 'expected_sha256': expected, 'attempts': attempts}
    return paths['links'], paths['queries'], results


def validate_resume(saved_config, current_config):
    """Prevent continuing features computed from other inputs or quality thresholds."""
    keys = ['hf_repo', 'resolved_revision', 'local_corpus_dir', 'max_files',
            'max_rows_per_file', 'min_chars', 'long_chars', 'seed']
    differences = [key for key in keys if saved_config.get(key) != current_config.get(key)]
    if saved_config.get('feature_version', 1) != current_config.get('feature_version', 1):
        differences.append('feature_version')
    if differences:
        raise ValueError('Không thể resume: cấu hình features khác ở ' + ', '.join(differences)
                         + '. Dùng lại cấu hình cũ hoặc tạo run mới.')


def save_reports(out, reports):
    for name, frame in reports.items():
        frame.to_csv(Path(out) / f'{name}.csv', index=False, encoding='utf-8-sig')


