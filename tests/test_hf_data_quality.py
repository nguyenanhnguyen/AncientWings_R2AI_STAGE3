"""Offline checks for dataset defects and standalone notebook generation."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
import io
from unittest.mock import Mock, patch

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hf_quality', ROOT / 'scripts' / 'hf_data_quality.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

CFG = {
    'min_chars': 200, 'long_chars': 30000, 'seed': 17, 'batch_size': 2,
    'max_rows_per_file': None, 'sample_size': 20, 'sample_char_cap': 30,
    'manual_per_stratum': 2, 'manual_random_cap': 20, 'manual_suspect_cap': 20,
}


def record(doc_id, text, url=None, **kwargs):
    return {'id': doc_id, 'url': url or f'https://medical.test/article/{doc_id}',
            'title': 'Medical article', 'text': text, 'status': 'extracted',
            'quality_status': 'accepted', 'char_count': len(text),
            'text_sha256': hashlib.sha256(text.encode()).hexdigest(), **kwargs}


class FeatureTests(unittest.TestCase):
    def feature(self, row):
        return audit.feature(row, 'corpus/test.parquet', 0, CFG)

    def test_valid_chinese_qa_not_whitespace_word_count(self):
        text = '患者咨询糖尿病治疗方法和药物使用问题。医生回答需要检查血糖和控制饮食。' * 10
        f = self.feature(record(1, text, lang='zh'))
        self.assertEqual(f['hard_flags'], '')
        self.assertEqual(f['script_hint'], 'cjk')
        self.assertGreater(f['approx_tokens'], 100)
        self.assertNotIn('language_metadata_suspect', f['review_flags'])

    def test_invalid_record_and_metadata_defects(self):
        row = record(True, '<div>Access denied �</div>', url='broken',
                     final_url='https://medical.test/', quality_flags=['crawler_review'])
        row.update(text_sha256='bad', char_count=999, status='failed', quality_status='rejected')
        f = self.feature(row)
        self.assertTrue({'invalid_id', 'invalid_url', 'text_sha256_mismatch',
                         'char_count_mismatch', 'failed_status_in_corpus', 'rejected_in_corpus'}
                        <= set(f['hard_flags'].split('|')))
        self.assertTrue({'html_leftover', 'encoding_suspect', 'block_or_error_page_suspect'}
                        <= set(f['review_flags'].split('|')))
        self.assertEqual(f['crawler_flags'], 'crawler_review')

    def test_null_and_empty_text(self):
        f = self.feature({'id': -1, 'url': None, 'text': None})
        self.assertIn('empty_text', f['hard_flags'])
        self.assertIsNone(f['norm_hash'])
        self.assertEqual(audit.to_id(str(2**80)), None)
        self.assertEqual(audit.to_id(1.5), None)

    def test_duplicate_normalization_preserves_numbers_and_accents(self):
        a = self.feature(record(1, 'Điều trị 20 mg &amp; nghỉ ngơi'))
        b = self.feature(record(2, ' ĐIỀU TRỊ 20 mg & nghỉ   ngơi '))
        c = self.feature(record(3, 'Điều trị 200 mg & nghỉ ngơi'))
        self.assertEqual(a['norm_hash'], b['norm_hash'])
        self.assertNotEqual(a['raw_hash'], b['raw_hash'])
        self.assertNotEqual(a['norm_hash'], c['norm_hash'])

    def test_question_answer_fallback_and_no_false_hash_semantics(self):
        row = {'id': 1, 'url': 'https://medical.test/a', 'question': 'Hỏi về sức khỏe',
               'answers': [{'text': 'Trả lời thứ nhất'}, {'content': 'Trả lời thứ hai'}],
               'text_sha256': 'ignored-for-reconstructed-text', 'char_count': 0}
        f = self.feature(row)
        self.assertIn('Trả lời thứ hai', f['preview'])
        self.assertNotIn('mismatch', f['hard_flags'])

    def test_redirect_and_repetitive_template_are_review_flags(self):
        text = '\n'.join(['Đăng nhập để xem toàn bộ bài viết liên quan.'] * 10)
        f = self.feature(record(1, text, final_url='https://medical.test/'))
        self.assertIn('homepage_redirect', f['review_flags'])
        self.assertIn('repeated_lines', f['review_flags'])
        self.assertEqual(f['hard_flags'], '')


@unittest.skipUnless(importlib.util.find_spec('pandas'), 'pandas is installed by the notebook')
class ScanTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        text = 'Bài viết hướng dẫn theo dõi đường huyết và chăm sóc sức khỏe hằng ngày. ' * 6
        first = [record(1, text, final_url='https://redirect.test/other'),
                 record(2, text), record(3, '')]
        second = [record(1, 'Nội dung đã thay đổi về điều trị bệnh.' * 8), record(99, 'Unknown source' * 30)]
        for name, rows in [('a.parquet', first), ('b.parquet', second)]:
            pq.write_table(pa.Table.from_pylist(rows), self.root / name, row_group_size=2)
        self.inventory, self.lookup = audit.scan_corpus(self.db, ['a.parquet', 'b.parquet'],
                                                       lambda name: self.root / name, CFG)

    def test_global_duplicate_conflict_and_empty_not_counted_as_duplicate(self):
        tables = audit.quality_tables(self.db)
        self.assertEqual(len(tables['duplicate_ids']), 1)
        self.assertEqual(int(tables['duplicate_ids'].iloc[0]['text_versions']), 2)
        self.assertEqual(int(tables['duplicate_text_groups'].iloc[0]['document_ids']), 2)
        self.assertFalse(tables['duplicate_text_groups']['norm_hash'].isna().any())
        self.assertEqual(sum(row['rows_scanned'] for row in self.inventory), 5)

    def test_source_unique_ids_and_original_domain_denominator(self):
        rows = [{'id': n, 'url': f'https://medical.test/article/{n}'} for n in [1, 2, 3, 4]]
        rows[1]['url'] = 'https://medical.test/original/2'
        pq.write_table(pa.Table.from_pylist(rows), self.root / 'links.parquet')
        tables, summary = audit.source_coverage(self.db, self.root / 'links.parquet', batch_size=2)
        self.assertEqual(summary['matched_ids'], 3) # ID 1 counted once across shards.
        self.assertEqual(summary['unknown_ids'], 1)
        self.assertEqual(summary['url_mismatch_rows'], 1)
        self.assertEqual(summary['link_coverage'], .75)
        coverage = tables['source_coverage_by_domain']
        self.assertEqual(coverage.iloc[0]['source_domain'], 'medical.test')
        self.assertEqual(coverage.iloc[0]['corpus_ids'], 3)

    def test_samples_rowgroups_cap_and_full_text_for_tokenizer(self):
        meta, sample, manual = audit.make_samples(self.db, self.lookup, CFG)
        self.assertEqual(len(sample), 5)
        self.assertTrue(sample['sample_truncated'].any())
        self.assertTrue((sample['text_sample'].str.len() <= 30).all())
        full = audit.load_selected(meta, self.lookup, batch_size=1)
        self.assertTrue((full['text_sample'].str.len() == full['chars']).all())
        self.assertIn('review_notes', manual)

    def test_prefix_limit_is_enforced_per_shard(self):
        limited = {**CFG, 'max_rows_per_file': 1}
        inventory, _ = audit.scan_corpus(self.db, ['a.parquet', 'b.parquet'],
                                        lambda name: self.root / name, limited)
        self.assertEqual([r['rows_scanned'] for r in inventory], [1, 1])

    @unittest.skipUnless(importlib.util.find_spec('sklearn'), 'scikit-learn is installed by the notebook')
    def test_query_probe_handles_empty_and_finds_matching_text(self):
        import pandas as pd
        _, sample, _ = audit.make_samples(self.db, self.lookup, {**CFG, 'sample_char_cap': 3000})
        queries = pd.DataFrame([{'id': 1, 'query': 'hướng dẫn theo dõi đường huyết'}])
        probe = audit.query_probe(queries, sample)
        self.assertGreater(len(probe), 0)
        self.assertGreater(probe.iloc[0]['tfidf_cosine'], 0)
        self.assertIn(int(probe.iloc[0]['doc_id']), [1, 2])
        empty = sample.iloc[:0].copy()
        self.assertTrue(audit.query_probe(queries, empty).empty)

    @unittest.skipUnless(importlib.util.find_spec('datasketch'), 'datasketch is installed by the notebook')
    def test_near_duplicate_is_verified_and_exact_duplicates_excluded(self):
        import pandas as pd
        text = 'Hướng dẫn kiểm tra huyết áp và chăm sóc sức khỏe ở người cao tuổi. ' * 10
        rows = [audit.feature(record(i, t), 'near.parquet', i, CFG) for i, t in
                [(1, text), (2, text + '!'), (3, text)]]
        sample = pd.DataFrame(rows)
        sample['text_sample'] = [text, text + '!', text]
        sample['sample_truncated'] = False
        pairs, hit = audit.near_duplicates(sample, .8, CFG['seed'])
        self.assertFalse(hit)
        self.assertGreaterEqual(len(pairs), 1)
        self.assertTrue((pairs['jaccard'] >= .8).all())
        self.assertNotIn((1, 3), set(zip(pairs['id_a'], pairs['id_b'])))


class NotebookTests(unittest.TestCase):
    def test_standalone_notebook_valid_clean_and_compiles(self):
        notebook = json.loads((ROOT / 'notebooks' / 'review_hf_data_quality.ipynb').read_text(encoding='utf-8'))
        if importlib.util.find_spec('nbformat'):
            import nbformat
            nbformat.validate(nbformat.from_dict(notebook))
        codes = [''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code']
        self.assertIn((ROOT / 'scripts' / 'hf_data_quality.py').read_text(encoding='utf-8').strip(),
                      '\n'.join(codes))
        for code in codes:
            compile(code, '<notebook>', 'exec')
        for cell in notebook['cells']:
            if cell['cell_type'] == 'code':
                self.assertEqual(cell['outputs'], [])
                self.assertIsNone(cell['execution_count'])

    @unittest.skipUnless(all(importlib.util.find_spec(name) for name in
        ['pandas', 'matplotlib', 'huggingface_hub', 'sklearn', 'datasketch']),
        'standalone notebook libraries are needed for the offline integration test')
    def test_missing_reference_exports_reports_and_resume_reuses_features(self):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        (ROOT / 'tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as scratch:
            root = Path(scratch)
            corpus = root / 'corpus'
            corpus.mkdir()
            pq.write_table(pa.Table.from_pylist([
                record(1, 'Bài hướng dẫn theo dõi đường huyết và sức khỏe. ' * 8),
                record(2, 'Kiểm tra huyết áp thường xuyên và vận động hợp lý. ' * 8),
            ]), corpus / 'fixture.parquet', row_group_size=1)
            notebook = json.loads((ROOT / 'notebooks/review_hf_data_quality.ipynb').read_text(encoding='utf-8'))

            def execute(resume=None):
                env = {'__name__': '__main__', 'test_root': root, 'test_corpus': corpus,
                       'test_resume': resume}
                with patch('huggingface_hub.hf_hub_download', side_effect=FileNotFoundError('404 fixture')), \
                     patch('huggingface_hub.get_token', return_value=None), \
                     patch('IPython.display.display'), patch.object(plt, 'show'), redirect_stdout(io.StringIO()):
                    for index, c in enumerate(notebook['cells']):
                        if c['cell_type'] != 'code':
                            continue
                        source = ''.join(c['source'])
                        if '# ===== CẤU HÌNH' in source:
                            source = source.replace('LOCAL_CORPUS_DIR = None', 'LOCAL_CORPUS_DIR = str(test_corpus)')
                            source = source.replace('RESUME_REVIEW_DIR = None', 'RESUME_REVIEW_DIR = test_resume')
                            source = source.replace("base = Path('/kaggle/working') if ON_KAGGLE else Path.cwd() / 'work'",
                                                    'base = test_root')
                            source += "\ncfg['sample_size']=2\nRUN_NEAR_DUPLICATES=False\n"
                        exec(compile(source, f'<integration-cell-{index}>', 'exec'), env)
                        if resume and 'def scan_corpus(' in source:
                            env['scan_corpus'] = Mock(side_effect=AssertionError('Resume must not rescan'))
                env['db'].close()
                plt.close('all')
                return env

            first = execute()
            summary = json.loads((first['OUT'] / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['source_coverage']['status'], 'skipped')
            self.assertIsNone(summary['source_coverage']['link_coverage'])
            self.assertFalse(summary['checks_run']['query_probe'])
            self.assertTrue((first['OUT'] / 'data_quality_review.zip').is_file())
            self.assertTrue((first['OUT'] / 'quality_flags.csv').is_file())
            self.assertIn('Chưa đo ID/URL/độ phủ', (first['OUT'] / 'REPORT.md').read_text(encoding='utf-8'))
            resumed = execute(str(first['OUT']))
            resumed['scan_corpus'].assert_not_called()
            self.assertEqual(resumed['total_rows'], first['total_rows'])


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, data in [('links_corpus.parquet', b'original links'), ('query.parquet', b'original query')]:
            (self.root / name).write_bytes(data)
        self.links_hash = audit.file_sha256(self.root / 'links_corpus.parquet')
        self.query_hash = audit.file_sha256(self.root / 'query.parquet')

    def test_404_links_does_not_block_identical_query_fallback(self):
        def download(repo, name, revision):
            if revision == 'replacement' and name == 'query.parquet':
                return self.root / name
            raise FileNotFoundError('404 fixture')
        links, queries, status = audit.prepare_source_files(download, 'repo', 'removed',
            self.links_hash, self.query_hash, query_fallback_revision='replacement')
        self.assertIsNone(links)
        self.assertEqual(queries, self.root / 'query.parquet')
        self.assertEqual(status['queries']['revision'], 'replacement')
        self.assertEqual(status['links']['status'], 'unavailable')

    def test_changed_reference_is_rejected_instead_of_compared(self):
        (self.root / 'links_corpus.parquet').write_bytes(b'new IDs or URLs')
        links, queries, status = audit.prepare_source_files(None, 'repo', 'old',
            self.links_hash, self.query_hash, local_dir=self.root)
        self.assertIsNone(links)
        self.assertIsNotNone(queries)
        self.assertEqual(status['links']['attempts'][0]['error'], 'sha256_mismatch')

    def test_original_local_files_are_accepted_without_network(self):
        remote = Mock(side_effect=AssertionError('Must not call HF for local source'))
        links, queries, status = audit.prepare_source_files(remote, 'repo', 'old',
            self.links_hash, self.query_hash, local_dir=self.root)
        self.assertEqual(status['links']['status'], 'ready')
        self.assertEqual(links, self.root / 'links_corpus.parquet')
        self.assertEqual(queries, self.root / 'query.parquet')
        remote.assert_not_called()

    def test_resume_accepts_sample_changes_but_rejects_changed_input_or_threshold(self):
        config = {'hf_repo': 'repo', 'resolved_revision': 'commit', 'min_chars': 200,
                  'long_chars': 30000, 'seed': 17}
        audit.validate_resume(config, {**config, 'sample_size': 100})
        with self.assertRaisesRegex(ValueError, 'resolved_revision'):
            audit.validate_resume(config, {**config, 'resolved_revision': 'other'})
        with self.assertRaisesRegex(ValueError, 'min_chars'):
            audit.validate_resume(config, {**config, 'min_chars': 300})


if __name__ == '__main__':
    unittest.main()

