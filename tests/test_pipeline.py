"""End-to-end check of blocks A4 to E on a fixture corpus, with no model download.

The dense channel uses the `hash` encoder and the reranker is `identity`, so the run needs neither
a GPU nor network access. That proves the plumbing — offsets, index/chunk pairing, submission
shape, metric arithmetic — and says nothing about retrieval quality, which is the point: a broken
pipeline should fail here rather than on the leaderboard.
"""
import argparse
import contextlib
import io
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import pyarrow as pa  # noqa: E402

from vibiomir.common import console, schema, storage  # noqa: E402
from vibiomir.corpus import chunk as chunking  # noqa: E402
from vibiomir.evaluation import errors, labels as label_tools, metrics  # noqa: E402
from vibiomir.evaluation import run as evaluation_cli  # noqa: E402
from vibiomir.index import build as index_cli  # noqa: E402
from vibiomir.retrieval import run as retrieval_cli  # noqa: E402
from vibiomir.submission import build as submission_cli  # noqa: E402
from vibiomir.submission import choose, validate  # noqa: E402

VI_BODY = (
    'Sỏi thận gây tắc nghẽn đường tiết niệu là một cấp cứu niệu khoa.\n\n'
    'Khi sỏi làm tắc niệu quản, người bệnh đau quặn thận dữ dội, lan xuống hố chậu. '
    'Cần giảm đau và dẫn lưu nước tiểu sớm để bảo vệ chức năng thận.\n\n'
    'Phương pháp xử trí gồm đặt ống thông JJ, dẫn lưu thận qua da, hoặc tán sỏi. '
    'Liều giảm đau thường dùng là 0,5 mg/kg, điều chỉnh theo đáp ứng và chức năng thận.\n\n'
    'Nếu có nhiễm khuẩn kèm theo, phải dùng kháng sinh đường tĩnh mạch và dẫn lưu ngay, '
    'không trì hoãn để chờ tán sỏi.'
)
ZH_BODY = (
    '肾结石引起尿路梗阻需要尽快处理。\n\n'
    '结石堵塞输尿管时会出现剧烈的肾区疼痛，并向下腹部放射。应当及早止痛并引流尿液。\n\n'
    '常用处理方式包括放置双J管、经皮肾穿刺引流以及体外冲击波碎石。合并感染时须静脉使用抗生素。'
)
EN_BODY = (
    'Obstructive uropathy from a kidney stone is a urological emergency.\n\n'
    'A stone lodged in the ureter causes severe flank pain radiating to the groin. '
    'Early analgesia and urinary drainage protect renal function.\n\n'
    'Management options include a JJ stent, percutaneous nephrostomy, or lithotripsy. '
    'Intravenous antibiotics are required when infection is present.'
)
SHORT_BODY = 'Tin ngắn về hội thảo tiết niệu.'


def _dp_lcs(left, right):
    """Plain dynamic programming, used only to check the bit-parallel implementation."""
    previous = [0] * (len(right) + 1)
    for token in left:
        current = [0]
        for position, other in enumerate(right):
            current.append(previous[position] + 1 if token == other
                           else max(current[position], previous[position + 1]))
        previous = current
    return previous[-1]


def write_fixture(root):
    documents = [
        {'id': 1584, 'url': 'https://example.vn/soi-than', 'title': 'Tắc nghẽn do sỏi thận',
         'text': VI_BODY, 'domain': 'example.vn'},
        {'id': 1585, 'url': 'https://example.cn/stone', 'title': '肾结石与尿路梗阻',
         'text': ZH_BODY, 'domain': 'example.cn'},
        {'id': 1586, 'url': 'https://example.org/stone', 'title': 'Obstructive uropathy',
         'text': EN_BODY, 'domain': 'example.org'},
        {'id': 1587, 'url': 'https://example.vn/tin', 'title': 'Hội thảo',
         'text': SHORT_BODY, 'domain': 'example.vn'},
    ]
    rows = [{field: document.get(field) for field in schema.DOCUMENT_FIELDS}
            for document in documents]
    for row in rows:
        row['duplicate_doc_ids'] = []
        row['text_sha256'] = storage.sha256_text(row['text'])
    corpus = root / 'corpus.parquet'
    storage.write_parquet(corpus, rows, schema=pa.schema(
        [(field, pa.int64() if field == 'id' else pa.list_(pa.int64())
          if field == 'duplicate_doc_ids' else pa.string()) for field in schema.DOCUMENT_FIELDS]))
    queries = root / 'query.parquet'
    storage.write_parquet(queries, [
        {'id': 1, 'query': 'Cần làm gì đối với tình trạng tắc nghẽn đường tiết niệu do sỏi thận?'},
        {'id': 2, 'query': 'Đau quặn thận dữ dội thì dùng thuốc giảm đau liều bao nhiêu ạ?'},
        {'id': 3, 'query': 'Sỏi thận có nhiễm khuẩn kèm theo thì xử trí thế nào?'},
    ], schema=pa.schema([('id', pa.int64()), ('query', pa.string())]))
    links = root / 'links_corpus.parquet'
    storage.write_parquet(links, [{'id': document['id'], 'url': document['url']}
                                  for document in documents],
                          schema=pa.schema([('id', pa.int64()), ('url', pa.string())]))
    return {'corpus': corpus, 'queries': queries, 'links': links, 'documents': documents}


class ChunkingTests(unittest.TestCase):
    def test_spans_are_exact_slices_and_sizes_are_bounded(self):
        document = {'id': 7, 'title': 'T', 'text': VI_BODY, 'domain': 'example.vn'}
        rows = chunking.chunk_document(document, target_tokens=40, overlap_tokens=10,
                                       max_tokens=80, min_tokens=5)
        text = schema.normalise_source(VI_BODY)
        self.assertGreater(len(rows), 1)
        for row in rows:
            self.assertEqual(row['text'], text[row['char_start']:row['char_end']])
            self.assertLessEqual(row['n_tokens'], 80)
            self.assertEqual(row['lang'], 'vi')
        self.assertEqual([row['chunk_order'] for row in rows], list(range(len(rows))))
        self.assertEqual(rows[0]['char_start'], 0)

    def test_chinese_is_detected_and_not_split_into_one_token(self):
        rows = chunking.chunk_document({'id': 8, 'title': '', 'text': ZH_BODY, 'domain': 'x'},
                                       target_tokens=40, overlap_tokens=8, max_tokens=80)
        self.assertTrue(rows)
        self.assertEqual(rows[0]['lang'], 'zh')
        self.assertGreater(rows[0]['n_tokens'], 10)

    def test_oversized_paragraph_is_subdivided_without_losing_text(self):
        body = 'Câu dài. ' * 400
        rows = chunking.chunk_document({'id': 9, 'title': '', 'text': body, 'domain': 'x'},
                                       target_tokens=60, overlap_tokens=0, max_tokens=120)
        text = schema.normalise_source(body)
        self.assertTrue(all(row['n_tokens'] <= 120 for row in rows))
        self.assertEqual(rows[0]['char_start'], 0)
        self.assertEqual(rows[-1]['char_end'], len(text))

    def test_title_is_kept_out_of_the_submitted_span(self):
        row = chunking.chunk_document({'id': 10, 'title': 'Tiêu đề', 'text': VI_BODY,
                                       'domain': 'x'})[0]
        self.assertNotIn('Tiêu đề', row['text'])
        self.assertTrue(chunking.retrieval_text(row).startswith('Tiêu đề'))


class MetricTests(unittest.TestCase):
    def test_bit_parallel_lcs_matches_dynamic_programming(self):
        generator = random.Random(42)
        for _ in range(400):
            alphabet = 'abcde'[:generator.randint(1, 5)]
            left = [generator.choice(alphabet) for _ in range(generator.randint(0, 14))]
            right = [generator.choice(alphabet) for _ in range(generator.randint(0, 14))]
            self.assertEqual(metrics.lcs_length(left, right), _dp_lcs(left, right),
                             msg=f'{left} vs {right}')

    def test_overlap_uses_the_reference_length_and_ignores_order_gaps(self):
        reference = schema.tokenize_for_match('liều giảm đau là 0,5 mg/kg')
        candidate = schema.tokenize_for_match('Liều giảm đau thường dùng là 0,5 mg/kg hôm nay')
        self.assertEqual(metrics.overlap(candidate, reference), 1.0)
        self.assertEqual(metrics.overlap(schema.tokenize_for_match('không liên quan'), reference),
                         0.0)

    def test_f2_weights_recall_and_matches_the_closed_form(self):
        self.assertAlmostEqual(metrics.f2(0.5, 0.5), 0.5)
        self.assertGreater(metrics.f2(0.2, 0.8), metrics.f2(0.8, 0.2))
        # F2 = 5k/(4g+N): two of four returned correct out of three references.
        score = metrics.score_documents([1, 2, 3, 4], [1, 2, 9])
        self.assertAlmostEqual(score['f2'], 5 * 2 / (4 * 3 + 4))

    def test_empty_prediction_scores_zero_not_an_error(self):
        score = metrics.score_documents([], [1, 2])
        self.assertEqual((score['precision'], score['recall'], score['f2']), (0.0, 0.0, 0.0))

    def test_chunk_recall_counts_distinct_references_once(self):
        reference = [{'doc_id': 1, 'chunk_text': 'liều giảm đau là 0,5 mg/kg theo đáp ứng'}]
        submitted = [{'doc_id': 1, 'chunk_text': 'liều giảm đau là 0,5 mg/kg theo đáp ứng thận'},
                     {'doc_id': 1, 'chunk_text': 'liều giảm đau là 0,5 mg/kg theo đáp ứng khác'}]
        score = metrics.score_chunks(submitted, reference)
        self.assertEqual(score['references_found'], 1)
        self.assertEqual(score['correct'], 2)
        self.assertEqual(score['recall'], 1.0)
        self.assertEqual(score['precision'], 1.0)

    def test_chunk_from_another_document_never_matches(self):
        reference = [{'doc_id': 1, 'chunk_text': 'liều giảm đau là 0,5 mg/kg'}]
        submitted = [{'doc_id': 2, 'chunk_text': 'liều giảm đau là 0,5 mg/kg'}]
        self.assertEqual(metrics.score_chunks(submitted, reference)['correct'], 0)

    def test_normalisation_follows_the_published_steps(self):
        self.assertEqual(schema.normalise_for_match('  A&amp;B  Ｃ  '), 'a&b c')


class SelectionTests(unittest.TestCase):
    def test_recall_profile_returns_more_than_precision_profile(self):
        record = {'query_id': 1,
                  'candidates': [{'chunk_id': f'{100 + i}:0', 'doc_id': 100 + i, 'chunk_order': 0,
                                  'rrf_score': 0.1, 'ce_score': 1.0 - i * 0.05}
                                 for i in range(20)],
                  'documents': [{'doc_id': 100 + i, 'score': 1.0 - i * 0.05} for i in range(20)]}
        generous, _ = choose.select_for_query(record, choose.policy('recall'))
        strict, _ = choose.select_for_query(record, choose.policy('precision'))
        self.assertGreater(len(generous), len(strict))

    def test_chunk_per_doc_caps_overlapping_windows(self):
        record = {'query_id': 1,
                  'candidates': [{'chunk_id': f'5:{i}', 'doc_id': 5, 'chunk_order': i,
                                  'rrf_score': 0.1, 'ce_score': 1.0 - i * 0.01} for i in range(8)],
                  'documents': [{'doc_id': 5, 'score': 1.0}]}
        _docs, chunks = choose.select_for_query(record, choose.policy('balanced'))
        self.assertEqual(len(chunks), choose.PROFILES['balanced']['chunk_per_doc'])

    def test_selected_chunk_documents_are_added_to_the_document_list(self):
        record = {'query_id': 1,
                  'candidates': [{'chunk_id': '42:0', 'doc_id': 42, 'chunk_order': 0,
                                  'rrf_score': 0.1, 'ce_score': 0.9}],
                  'documents': [{'doc_id': 7, 'score': 1.0}]}
        docs, _chunks = choose.select_for_query(record, choose.policy('balanced'))
        self.assertIn(42, docs)
        docs, _chunks = choose.select_for_query(record, choose.policy('balanced',
                                                                     sync_docs=False))
        self.assertNotIn(42, docs)


class PipelineTests(unittest.TestCase):
    def test_full_flow_produces_a_valid_submission_and_scores_it(self):
        with tempfile.TemporaryDirectory(prefix='vibiomir-pipeline-') as temporary:
            root = Path(temporary)
            fixture = write_fixture(root)
            work = root / 'work'

            chunking.build(argparse.Namespace(
                corpus=[str(fixture['corpus'])], out=str(work / 'chunks'), target_tokens=60,
                overlap_tokens=15, max_tokens=120, min_tokens=8, text_field=None, status='ok'))
            chunks_file = work / 'chunks' / 'chunks.parquet'
            self.assertTrue(chunks_file.is_file())

            index_args = argparse.Namespace(
                chunks=str(chunks_file), out=str(work / 'index'), k1=1.5, b=0.75,
                encoder='hash', device='cpu', batch_size=4, shard=8, fp32=True,
                faiss=False, faiss_lists=0)
            index_cli.build_all(index_args)
            self.assertTrue((work / 'index' / 'bm25.npz').is_file())
            self.assertTrue((work / 'index' / 'embeddings.npy').is_file())

            retrieval_cli.run(argparse.Namespace(
                chunks=str(chunks_file), index=str(work / 'index'),
                queries=str(fixture['queries']), out=str(work / 'retrieval'),
                top_k=20, fuse_k=20, rerank_k=20, keep=10, doc_chunks=3,
                encoder=None, reranker='identity', weights=None, keyword_variant=True,
                translations=None, no_bm25=False, no_dense=False, faiss=False,
                device='cpu', batch_size=4, rerank_batch=4, fp32=True))
            candidates = work / 'retrieval' / 'candidates.jsonl'
            records = storage.read_jsonl(candidates)
            self.assertEqual(len(records), 3)
            self.assertTrue(all(record['candidates'] for record in records))

            submission_cli.build(argparse.Namespace(
                candidates=str(candidates), chunks=str(chunks_file),
                corpus=[str(fixture['corpus'])], queries=str(fixture['queries']),
                links=str(fixture['links']), out=str(work / 'submission'),
                name='submission.json', profile='balanced', adaptive=True, no_sync_docs=False,
                doc_min=None, doc_max=None, doc_ratio=None, chunk_min=None, chunk_max=None,
                chunk_ratio=None, chunk_per_doc=None, doc_id_as_string=False, text_field=None))

            rows = storage.read_json(work / 'submission' / 'submission.json')
            self.assertEqual([row['id'] for row in rows], [1, 2, 3])
            self.assertEqual(schema.validate_submission_shape(rows, [1, 2, 3]), [])
            texts = {document['id']: schema.normalise_source(document['text'])
                     for document in fixture['documents']}
            for row in rows:
                self.assertTrue(row['relevant_docs'])
                self.assertTrue(row['relevant_chunks'])
                for item in row['relevant_chunks']:
                    self.assertIsInstance(item['doc_id'], int)
                    self.assertIn(item['chunk_text'], texts[item['doc_id']])
                    self.assertLessEqual(schema.count_tokens(item['chunk_text']), 1024)

            with zipfile.ZipFile(work / 'submission' / 'submission.zip') as archive:
                self.assertEqual(archive.namelist(), ['submission.json'])
                self.assertEqual(json.loads(archive.read('submission.json')), rows)

            evaluation_cli.pseudo(argparse.Namespace(
                candidates=str(candidates), chunks=str(chunks_file), out=str(work / 'eval'),
                top_n=2))
            summary = evaluation_cli.score(argparse.Namespace(
                submission=str(work / 'submission' / 'submission.json'),
                labels=str(work / 'eval' / 'labels.jsonl'), candidates=str(candidates),
                corpus=[str(fixture['corpus'])], out=str(work / 'eval')))
            self.assertEqual(summary['queries_scored'], 3)
            # Pseudo labels are the pipeline's own top chunks, so recall must be high here; this
            # asserts the metric wiring, not retrieval quality.
            self.assertGreater(summary['chunk_recall'], 0.5)
            self.assertTrue((work / 'eval' / 'EVAL_REPORT.md').is_file())

    def test_index_built_from_another_chunk_file_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='vibiomir-pair-') as temporary:
            root = Path(temporary)
            fixture = write_fixture(root)
            work = root / 'work'
            chunking.build(argparse.Namespace(
                corpus=[str(fixture['corpus'])], out=str(work / 'chunks'), target_tokens=60,
                overlap_tokens=15, max_tokens=120, min_tokens=8, text_field=None, status='ok'))
            chunks_file = work / 'chunks' / 'chunks.parquet'
            index_cli.build_bm25(argparse.Namespace(
                chunks=str(chunks_file), out=str(work / 'index'), k1=1.5, b=0.75))
            chunking.build(argparse.Namespace(
                corpus=[str(fixture['corpus'])], out=str(work / 'chunks2'), target_tokens=30,
                overlap_tokens=5, max_tokens=60, min_tokens=8, text_field=None, status='ok'))
            with self.assertRaisesRegex(ValueError, 'different chunks file'):
                retrieval_cli._check_pair(work / 'chunks2' / 'chunks.parquet', work / 'index')

    def test_tampered_chunk_text_fails_the_reslice_check(self):
        with tempfile.TemporaryDirectory(prefix='vibiomir-reslice-') as temporary:
            root = Path(temporary)
            fixture = write_fixture(root)
            chunking.build(argparse.Namespace(
                corpus=[str(fixture['corpus'])], out=str(root / 'chunks'), target_tokens=60,
                overlap_tokens=15, max_tokens=120, min_tokens=8, text_field=None, status='ok'))
            table = validate.load_chunk_table(root / 'chunks' / 'chunks.parquet')
            documents = validate.load_document_texts([fixture['corpus']])
            first = next(iter(table))
            table[first] = {**table[first], 'text': 'Nội dung do hệ thống tự viết lại.'}
            chosen = {1: ([table[first]['doc_id']],
                          [{'doc_id': table[first]['doc_id'], 'chunk_id': first,
                            'chunk_order': table[first]['chunk_order'], 'score': 1.0}])}
            with self.assertRaisesRegex(ValueError, 'does not re-slice'):
                validate.build_rows(chosen, table, documents, [1])

    def test_document_outside_links_corpus_never_reaches_the_submission(self):
        with tempfile.TemporaryDirectory(prefix='vibiomir-links-') as temporary:
            root = Path(temporary)
            fixture = write_fixture(root)
            chunking.build(argparse.Namespace(
                corpus=[str(fixture['corpus'])], out=str(root / 'chunks'), target_tokens=60,
                overlap_tokens=15, max_tokens=120, min_tokens=8, text_field=None, status='ok'))
            table = validate.load_chunk_table(root / 'chunks' / 'chunks.parquet')
            documents = validate.load_document_texts([fixture['corpus']])
            chunk_id = next(key for key, row in table.items() if row['doc_id'] == 1585)
            # 1585 is in the corpus but excluded from the official id list for this check: it must
            # not slip in through relevant_docs, not as a document and not via its own chunk.
            chosen = {1: ([1584, 1585], [{'doc_id': 1585, 'chunk_id': chunk_id,
                                          'chunk_order': table[chunk_id]['chunk_order'],
                                          'score': 1.0}])}
            rows, report = validate.build_rows(chosen, table, documents, [1],
                                               allowed_doc_ids={1584, 1586, 1587})
            self.assertEqual(rows[0]['relevant_docs'], [1584])
            self.assertEqual(report['dropped_docs'], 1)


class LossAttributionTests(unittest.TestCase):
    def test_each_cause_is_attributed_to_its_own_block(self):
        labels = {
            1: {'docs': [900], 'chunks': []},                       # not crawled
            2: {'docs': [10], 'chunks': []},                        # retrieved by nobody
            3: {'docs': [11], 'chunks': []},                        # candidate, not selected
            4: {'docs': [12], 'chunks': [{'doc_id': 12,
                                          'chunk_text': 'một đoạn tham chiếu hoàn toàn khác'}]},
        }
        records = [
            {'query_id': 1, 'query': '', 'candidates': [], 'documents': []},
            {'query_id': 2, 'query': '', 'candidates': [], 'documents': []},
            {'query_id': 3, 'query': '', 'candidates': [{'chunk_id': '11:0', 'doc_id': 11}],
             'documents': []},
            {'query_id': 4, 'query': '', 'candidates': [{'chunk_id': '12:0', 'doc_id': 12}],
             'documents': []},
        ]
        rows = [
            {'id': 1, 'relevant_docs': [], 'relevant_chunks': []},
            {'id': 2, 'relevant_docs': [], 'relevant_chunks': []},
            {'id': 3, 'relevant_docs': [], 'relevant_chunks': []},
            {'id': 4, 'relevant_docs': [12],
             'relevant_chunks': [{'doc_id': 12, 'chunk_text': 'nội dung không trùng'}]},
        ]
        summary, cases = errors.classify(labels, records, rows, {10, 11, 12})
        self.assertEqual(summary['losses'], {'not_crawled': 1, 'not_retrieved': 1,
                                             'not_selected': 1, 'chunk_too_narrow': 1})
        self.assertEqual({case['cause'] for case in cases}, set(errors.CAUSES))
        self.assertIn('Block A', errors.report_markdown(
            summary, {'document_precision': 0.0, 'document_recall': 0.0, 'document_f2': 0.0,
                      'chunk_precision': None, 'chunk_recall': None, 'chunk_f2': None,
                      'queries_scored': 4}, ['human']))

    def test_pseudo_labels_are_flagged_in_the_report(self):
        summary = {'losses': {cause: 0 for cause in errors.CAUSES},
                   'loss_share': {cause: None for cause in errors.CAUSES},
                   'documents_found': 0, 'reference_documents': 0, 'biggest_loss': None,
                   'false_positive_documents': 0, 'submitted_documents': 0}
        report = errors.report_markdown(summary, {'queries_scored': 0}, ['pseudo'])
        self.assertIn('vòng tròn', report)


class CorpusShapeTests(unittest.TestCase):
    """Preprocessing may hand over rows of different shape; chunking and D2 must agree on all."""

    def _run(self, rows, text_field=None):
        with tempfile.TemporaryDirectory(prefix='vibiomir-shape-') as temporary:
            root = Path(temporary)
            source = root / 'corpus.jsonl'
            storage.write_jsonl(source, rows)
            chunking.build(argparse.Namespace(
                corpus=[str(source)], out=str(root / 'chunks'), target_tokens=40,
                overlap_tokens=8, max_tokens=80, min_tokens=5, text_field=text_field, status='ok'))
            table = validate.load_chunk_table(root / 'chunks' / 'chunks.parquet')
            documents = validate.load_document_texts([source], text_field)
            for row in table.values():
                self.assertEqual(documents[row['doc_id']][row['char_start']:row['char_end']],
                                 row['text'])
            return table

    def test_extra_missing_and_null_columns_are_tolerated(self):
        table = self._run([{'id': 1, 'text': VI_BODY, 'extra': {'x': 1}},
                           {'id': 2, 'text': None, 'title': None},
                           {'id': 3, 'content': VI_BODY, 'title': None}])
        self.assertEqual({row['doc_id'] for row in table.values()}, {1, 3})

    def test_renamed_body_column_needs_no_code_change(self):
        table = self._run([{'id': 1, 'html_text': VI_BODY}], text_field='html_text')
        self.assertTrue(table)

    def test_question_and_answers_are_joined_without_invented_labels(self):
        row = {'id': 5, 'question': 'Đau họng kéo dài thì sao?',
               'answers': ['Nên uống nước ấm.', {'text': 'Khám nếu sốt cao.'}]}
        text = schema.document_text(row)
        self.assertEqual(text.split(chr(10) * 2),
                         ['Đau họng kéo dài thì sao?', 'Nên uống nước ấm.', 'Khám nếu sốt cao.'])
        self.assertNotIn('Câu hỏi', text)
        self.assertTrue(self._run([{**row, 'question': row['question'] * 6}]))

    def test_team_crawler_json_array_with_failed_rows_is_read_as_is(self):
        """crawler_minh exports a JSON array whose rows carry status; failures have no text."""
        with tempfile.TemporaryDirectory(prefix='vibiomir-team-') as temporary:
            root = Path(temporary)
            source = root / 'batch_00.json'
            rows = [{'id': 1, 'url': 'u', 'status': 'ok', 'lang': 'vi', 'n_chars': 10,
                     'title': 'T', 'text': VI_BODY, 'domain': 'a.vn', 'canonical_id': 1,
                     'dup_count': 1, 'worker': 'Minh', 'batch': 0},
                    {'id': 2, 'url': 'u', 'status': 'http_4xx', 'text': '', 'title': ''},
                    {'id': 3, 'url': 'u', 'status': 'blocked', 'text': None}]
            source.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
            summary = chunking.build(argparse.Namespace(
                corpus=[str(source)], out=str(root / 'chunks'), target_tokens=40,
                overlap_tokens=8, max_tokens=80, min_tokens=5, text_field=None, status='ok'))
            self.assertEqual(summary['documents_in'], 1)
            self.assertEqual(summary['rows_skipped_by_status'], 2)
            self.assertEqual(set(validate.load_document_texts([source])), {1, 2, 3})

    def test_string_ids_are_unified_with_integer_ids(self):
        table = self._run([{'id': '12', 'text': VI_BODY}, {'id': 12, 'text': ZH_BODY}])
        self.assertEqual({row['doc_id'] for row in table.values()}, {12})
        self.assertEqual(sum(1 for _ in table), len([k for k in table]))

    def test_unrecognised_shape_fails_loudly_with_the_fix_in_the_message(self):
        with self.assertRaisesRegex(ValueError, 'text column'):
            self._run([{'id': 1, 'noi_dung': VI_BODY}])


class ConsoleTests(unittest.TestCase):
    def test_vietnamese_output_survives_a_cp1252_console(self):
        """A Windows console defaults to cp1252; a report must not die on its first diacritic."""
        narrow = io.TextIOWrapper(io.BytesIO(), encoding='cp1252', errors='strict')
        with contextlib.redirect_stdout(narrow):
            console.emit('Nộp file: work/submission/submission.zip')
            console.emit('CẢNH BÁO: nhãn pseudo')
        narrow.seek(0)
        written = narrow.buffer.getvalue().decode('cp1252')
        self.assertIn('file: work/submission/submission.zip', written)
        self.assertIn('BÁO', written.replace('\\u1ea2', 'Ả'))

    def test_utf8_console_keeps_the_text_intact(self):
        wide = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
        with contextlib.redirect_stdout(wide):
            console.emit('Nộp file')
        wide.seek(0)
        self.assertEqual(wide.buffer.getvalue().decode('utf-8').strip(), 'Nộp file')


class LabelSheetTests(unittest.TestCase):
    def test_sheet_round_trips_into_labels_and_skips_unmarked_queries(self):
        with tempfile.TemporaryDirectory(prefix='vibiomir-labels-') as temporary:
            root = Path(temporary)
            records = [{'query_id': 1, 'query': 'câu hỏi', 'documents': [],
                        'candidates': [{'chunk_id': '5:0', 'doc_id': 5},
                                       {'chunk_id': '6:0', 'doc_id': 6}]},
                       {'query_id': 2, 'query': 'câu hỏi khác', 'documents': [],
                        'candidates': [{'chunk_id': '7:0', 'doc_id': 7}]}]
            table = {'5:0': {'text': 'đoạn A'}, '6:0': {'text': 'đoạn B'},
                     '7:0': {'text': 'đoạn C'}}
            sheet = label_tools.write_label_sheet(records, table, root, per_query=5)
            with self.assertRaises(FileExistsError):
                label_tools.write_label_sheet(records, table, root)
            rows = storage.read_jsonl(sheet)
            rows[0]['candidates'][0]['relevant'] = True
            rows[0]['candidates'][1]['relevant'] = False
            rows[0]['annotator'] = 'nguyen'
            storage.write_jsonl(sheet, rows)
            summary = label_tools.labels_from_sheet(sheet, root / 'labels.jsonl')
            self.assertEqual(summary['labelled_queries'], 1)
            self.assertEqual(summary['unmarked_queries_skipped'], 1)
            table, sources = label_tools.load_labels(root / 'labels.jsonl')
            self.assertEqual(sources, ['human'])
            self.assertEqual(table[1]['docs'], [5])


if __name__ == '__main__':
    unittest.main()
