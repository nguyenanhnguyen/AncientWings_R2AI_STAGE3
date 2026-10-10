"""Offline tests for the cascade design: sources, cards, subset, card channel, F2 cut, windows."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pyarrow as pa  # noqa: E402

from vibiomir.common import schema, storage  # noqa: E402
from vibiomir.corpus import cards, chunk as chunking, prepare  # noqa: E402
from vibiomir.index import build as index_cli  # noqa: E402
from vibiomir.retrieval import query as query_tools, run as retrieval_cli  # noqa: E402
from vibiomir.submission import calibrate, choose, validate  # noqa: E402
from test_pipeline import write_fixture  # noqa: E402

LONG = '\n\n'.join(f'Đoạn {i}: ' + 'sỏi thận gây đau và cần điều trị sớm. ' * 12 for i in range(12))


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


class SourceDiscoveryTests(unittest.TestCase):
    def test_crawl_folder_is_expanded_to_its_runs_without_walking_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'nguyen'
            for run in ('output/runs/batch01', 'shards/shard_01/runs/s1'):
                (root / run / 'records').mkdir(parents=True)
            # A stray links_corpus copy next to the runs must not become a source.
            (root / 'output' / 'data').mkdir(parents=True)
            storage.write_parquet(root / 'output/data/links_corpus.parquet', [{'id': 1}])
            found = prepare.discover_sources(root)
            self.assertEqual([p.relative_to(root).as_posix() for p in found],
                             ['output/runs/batch01', 'shards/shard_01/runs/s1'])

    def test_limit_is_shared_over_runs_by_size(self):
        self.assertEqual(prepare.proportional_quotas([137, 87, 107], 100), [42, 26, 32])
        self.assertEqual(prepare.proportional_quotas([5, 3], 100), [5, 3])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'nguyen'
            ids = {'output/runs/a': range(100, 160), 'shards/s1/runs/b': range(500, 530),
                   'shards/s2/runs/c': range(900, 910)}
            for run, numbers in ids.items():
                (root / run / 'records').mkdir(parents=True)
                for i in numbers:
                    storage.write_json(root / run / 'records' / f'{i}.json',
                                       {'id': i, 'url': f'https://x.vn/bai-{i}', 'status': 'extracted',
                                        'quality_status': 'accepted', 'text': f'Bài số {i} về sỏi thận.'})
            with quiet():
                summary = prepare.build(argparse.Namespace(
                    source=[str(root)], out=str(Path(tmp) / 'out'), limit=20, split='proportional',
                    max_duplicates=20, min_chars=0, drop_review=False, text_field=None))
            self.assertEqual(sorted(summary['rows_read_per_source'].values()), [2, 6, 12])
            self.assertEqual(summary['rows_read'], 20)
            ids_kept = [row['id'] for row in storage.read_parquet(Path(tmp) / 'out' / 'corpus.parquet')]
            # Lowest ids of each run.
            self.assertEqual(ids_kept, list(range(100, 112)) + list(range(500, 506)) + [900, 901])

    def test_parquet_folder_contributes_each_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'corpus'
            for name in ('ids_1_2_synced', 'ids_3_4_synced'):
                storage.write_parquet(folder / f'{name}.parquet', [{'id': 1, 'text': 'x'}])
            self.assertEqual([p.name for p in prepare.discover_sources(folder)],
                             ['ids_1_2_synced.parquet', 'ids_3_4_synced.parquet'])


class WindowTests(unittest.TestCase):
    def test_window_is_an_exact_slice_within_budget_containing_the_seed(self):
        text = schema.normalise_source(LONG)
        spans = chunking.plan_spans(text, target_tokens=60, overlap_tokens=10, max_tokens=120)
        for start, end in spans:
            ws, we = chunking.expand_window(text, start, end, 300)
            self.assertLessEqual(ws, start)
            self.assertGreaterEqual(we, end)
            self.assertLessEqual(schema.count_tokens(text[ws:we]), 300)
            self.assertGreater(schema.count_tokens(text[ws:we]), schema.count_tokens(text[start:end]))

    def test_short_document_becomes_one_window(self):
        text = 'Câu một.\n\nCâu hai về sỏi thận.\n\nCâu ba.'
        self.assertEqual(chunking.expand_window(text, 10, 30, 768), (0, len(text)))

    def test_zero_budget_keeps_the_chunk(self):
        self.assertEqual(chunking.expand_window('a b c', 0, 3, 0), (0, 3))

    def test_lead_span_stops_at_the_budget(self):
        text = schema.normalise_source(LONG)
        start, end = chunking.lead_span(text, 50)
        self.assertEqual(start, 0)
        self.assertLessEqual(schema.count_tokens(text[start:end]), 120)
        self.assertTrue(text[start:end].startswith('Đoạn 0'))

    def test_submission_widens_and_drops_chunks_inside_a_window(self):
        text = schema.normalise_source(LONG)
        spans = chunking.plan_spans(text, target_tokens=60, overlap_tokens=0, max_tokens=120)
        table = {f'9:{i}': {'doc_id': 9, 'text': text[s:e], 'char_start': s, 'char_end': e,
                            'chunk_order': i} for i, (s, e) in enumerate(spans)}
        chosen = {1: ([9], [{'doc_id': 9, 'chunk_id': '9:1'}, {'doc_id': 9, 'chunk_id': '9:2'}])}
        rows, report = validate.build_rows(chosen, table, {9: text}, [1], window_tokens=400)
        submitted = rows[0]['relevant_chunks']
        self.assertEqual(len(submitted), 1)  # chunk 2 sits inside chunk 1's window
        self.assertEqual(report['chunks_inside_window'], 1)
        self.assertIn(table['9:1']['text'], submitted[0]['chunk_text'])
        self.assertIn(submitted[0]['chunk_text'], text)
        self.assertLessEqual(schema.count_tokens(submitted[0]['chunk_text']), 400)


class F2SelectionTests(unittest.TestCase):
    def test_cut_matches_brute_force_expected_f2(self):
        rng = np.random.default_rng(0)
        for _ in range(50):
            probs = sorted(rng.random(12) ** 3, reverse=True)
            total = sum(probs)
            best = max(range(1, 13), key=lambda k: sum(probs[:k]) / (4 * total + k))
            self.assertEqual(choose.f2_cut(probs, 1, 12), best)

    def test_profile_takes_likely_items_and_documents_follow_chunks(self):
        scores = [0.95, 0.9, 0.4, 0.02, 0.01, 0.01]
        record = {'query_id': 1, 'candidates': [
            {'chunk_id': f'{i}:0', 'doc_id': i, 'chunk_order': 0, 'rrf_score': 0.01,
             'ce_score': s, 'lang': 'vi'} for i, s in enumerate(scores, start=1)],
            'documents': []}
        docs, chunks = choose.select_for_query(record, choose.policy('f2'))
        self.assertEqual([c['doc_id'] for c in chunks], [1, 2, 3])
        self.assertEqual(docs, [1, 2, 3])

    def test_calibration_fit_recovers_a_shift(self):
        rng = np.random.default_rng(1)
        logits = rng.normal(0, 2, 4000)
        labels = (rng.random(4000) < 1 / (1 + np.exp(-(logits - 2)))).astype(int)
        scores = 1 / (1 + np.exp(-logits))
        a, b = calibrate.fit_platt(scores, labels)
        self.assertAlmostEqual(a, 1.0, delta=0.15)
        self.assertAlmostEqual(b, -2.0, delta=0.3)
        self.assertLess(calibrate.apply(0.5, 'zh', {'default': [a, b]}), 0.3)


class TranslationVariantTests(unittest.TestCase):
    def test_hyde_rows_become_their_own_variants_and_old_files_still_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 't.jsonl'
            storage.write_jsonl(path, [{'id': 1, 'lang': 'zh', 'text': '肾结石怎么办'},
                                       {'id': 1, 'lang': 'vi', 'kind': 'hyde', 'text': 'Sỏi thận cần...'}])
            table = query_tools.load_translations(path)
            self.assertEqual(sorted(table), ['hyde_vi', 'translated_zh'])
            names = query_tools.variants({'id': 1, 'query': 'Sỏi thận?'}, translations=table)
            self.assertEqual(list(names), ['original', 'translated_zh', 'hyde_vi'])
            self.assertEqual(query_tools.variant_language('hyde_vi'), 'vi')

    def test_reranker_reads_the_question_in_the_chunk_language(self):
        query = {'id': 1, 'query': 'Sỏi thận?'}
        table = {'original': 'Sỏi thận?', 'translated_zh': '肾结石？'}
        self.assertEqual(retrieval_cli._rerank_query(query, table, 'zh', True), '肾结石？')
        self.assertEqual(retrieval_cli._rerank_query(query, table, 'vi', True), 'Sỏi thận?')
        self.assertEqual(retrieval_cli._rerank_query(query, table, 'zh', False), 'Sỏi thận?')


class CascadeTests(unittest.TestCase):
    def test_cards_subset_and_card_channel_end_to_end(self):
        with tempfile.TemporaryDirectory(prefix='vibiomir-cascade-') as tmp:
            root = Path(tmp)
            fixture = write_fixture(root)
            with quiet():
                chunking.build(argparse.Namespace(
                    corpus=[str(fixture['corpus'])], out=str(root / 'chunks'), target_tokens=60,
                    overlap_tokens=15, max_tokens=120, min_tokens=8, text_field=None, status='ok'))
                cards.build(argparse.Namespace(corpus=[str(fixture['corpus'])],
                                               out=str(root / 'cards'), lead_tokens=40,
                                               text_field=None))
            card_rows = storage.read_parquet(root / 'cards' / 'cards.parquet')
            self.assertEqual(len(card_rows), 4)
            texts = {d['id']: schema.normalise_source(d['text']) for d in fixture['documents']}
            for card in card_rows:
                self.assertEqual(texts[card['doc_id']][card['char_start']:card['char_end']], card['text'])
            index = argparse.Namespace(k1=1.5, b=0.75, encoder='hash', device='cpu', batch_size=4,
                                       shard=8, fp32=True, faiss=False, faiss_lists=0)
            common = dict(queries=str(fixture['queries']), top_k=2, fuse_k=2, rerank_k=2, keep=2,
                          doc_chunks=3, encoder=None, reranker='identity', weights=None,
                          keyword_variant=False, translations=None, no_bm25=False,
                          no_dense=False, faiss=False, device='cpu', batch_size=4,
                          rerank_batch=4, fp32=True)
            with quiet():
                index_cli.build_all(argparse.Namespace(chunks=str(root / 'cards' / 'cards.parquet'),
                                                       out=str(root / 'icards'), **vars(index)))
                retrieval_cli.run(argparse.Namespace(chunks=str(root / 'cards' / 'cards.parquet'),
                                                     index=str(root / 'icards'),
                                                     out=str(root / 'docs'), **common))
                cards.subset(argparse.Namespace(candidates=[str(root / 'docs' / 'candidates.jsonl')],
                                                corpus=[str(fixture['corpus'])],
                                                out=str(root / 'subset'), docs_per_query=2,
                                                target_tokens=60, overlap_tokens=15,
                                                max_tokens=120, min_tokens=8, text_field=None))
            ranked = storage.read_jsonl(root / 'subset' / 'doc_candidates.jsonl')
            self.assertEqual(len(ranked), 3)
            wanted = {d for row in ranked for d in row['doc_ids']}
            subset = storage.read_parquet(root / 'subset' / 'chunks.parquet')
            self.assertEqual({row['doc_id'] for row in subset}, wanted)
            # Chunking only the candidates gives exactly the chunks a full chunking would.
            full = {row['chunk_id']: row for row in storage.read_parquet(root / 'chunks' / 'chunks.parquet')}
            self.assertEqual(len(subset), sum(row['doc_id'] in wanted for row in full.values()))
            self.assertTrue(all(full[row['chunk_id']] == row for row in subset))
            with quiet():
                index_cli.build_all(argparse.Namespace(chunks=str(root / 'subset' / 'chunks.parquet'),
                                                       out=str(root / 'isub'), **vars(index)))
                retrieval_cli.run(argparse.Namespace(
                    chunks=str(root / 'subset' / 'chunks.parquet'), index=str(root / 'isub'),
                    out=str(root / 'ret'), doc_candidates=str(root / 'subset' / 'doc_candidates.jsonl'),
                    match_language=True, shard=1, shards=2,
                    **{**common, 'top_k': 20, 'fuse_k': 20, 'rerank_k': 20, 'keep': 20}))
            records = storage.read_jsonl(root / 'ret' / 'candidates.jsonl')
            self.assertEqual([r['query_id'] for r in records], [2])  # shard 1 of 2: second query
            self.assertTrue(any('card' in c['channels'] for c in records[0]['candidates']))
            self.assertTrue(all('lang' in c for c in records[0]['candidates']))

    def test_dense_parts_merge_into_the_single_run_matrix(self):
        with tempfile.TemporaryDirectory(prefix='vibiomir-parts-') as tmp:
            root = Path(tmp)
            fixture = write_fixture(root)
            with quiet():
                chunking.build(argparse.Namespace(
                    corpus=[str(fixture['corpus'])], out=str(root / 'chunks'), target_tokens=60,
                    overlap_tokens=15, max_tokens=120, min_tokens=8, text_field=None, status='ok'))
                chunks = str(root / 'chunks' / 'chunks.parquet')
                base = dict(chunks=chunks, encoder='hash', device='cpu', batch_size=2, shard=3,
                            fp32=True, faiss=False, faiss_lists=0, resume=False)
                index_cli.build_dense(argparse.Namespace(out=str(root / 'one'), **base))
                for part in range(3):
                    index_cli.build_dense(argparse.Namespace(out=str(root / 'many'), part=part,
                                                             parts=3, **base))
                index_cli.merge_dense(argparse.Namespace(out=str(root / 'many'), parts=3, **base))
            single = np.load(root / 'one' / 'embeddings.npy')
            merged = np.load(root / 'many' / 'embeddings.npy')
            np.testing.assert_array_equal(single, merged)
            manifest = storage.read_json(root / 'many' / 'dense_manifest.json')
            self.assertEqual(manifest['chunks_sha256'], storage.sha256_file(chunks))


class FetchTests(unittest.TestCase):
    def _fake_hub(self, root, links_rows):
        def hf_hub_download(repo, name, repo_type, revision, local_dir):
            path = Path(local_dir) / name
            rows = links_rows if name == 'links_corpus.parquet' else [{'id': 1, 'query': 'Sỏi thận?'}]
            storage.write_parquet(path, rows)
            return str(path)

        def snapshot_download(repo, repo_type, revision, allow_patterns, local_dir):
            storage.write_parquet(Path(local_dir) / 'corpus' / 'ids_1_2_synced.parquet',
                                  [{'id': 1, 'text': 'a'}, {'id': 2, 'text': 'b'}])
            return local_dir
        return hf_hub_download, snapshot_download

    def test_pin_keeps_the_first_commit_and_refuses_another(self):
        from vibiomir.corpus import fetch
        with tempfile.TemporaryDirectory() as tmp:
            sha = 'a' * 40
            self.assertEqual(fetch.resolve_revision(tmp, 'team/ds', sha), sha)
            fetch.pin(tmp, 'team/ds', sha)
            self.assertEqual(fetch.resolve_revision(tmp, 'team/ds', None), sha)
            with self.assertRaisesRegex(ValueError, 'pinned'):
                fetch.resolve_revision(tmp, 'team/ds', 'b' * 40)

    def test_fetch_writes_the_layout_and_rejects_other_links(self):
        from unittest.mock import patch
        import huggingface_hub
        from vibiomir.corpus import fetch
        with tempfile.TemporaryDirectory() as tmp:
            down, snap = self._fake_hub(tmp, [{'id': 1}, {'id': 2}])
            args = argparse.Namespace(out=tmp, repo='team/ds', revision='c' * 40)
            with patch.object(huggingface_hub, 'hf_hub_download', down), \
                 patch.object(huggingface_hub, 'snapshot_download', snap), quiet():
                with self.assertRaisesRegex(ValueError, 'SHA-256'):
                    fetch.fetch(args)
                with patch.object(fetch, 'LINKS_SHA256', storage.sha256_file(Path(tmp) / 'source' / 'links_corpus.parquet')):
                    summary = fetch.fetch(args)
            self.assertEqual((summary['corpus_files'], summary['corpus_rows']), (1, 2))
            paths = fetch.layout(tmp, 'c' * 40)
            self.assertTrue(paths['corpus'].is_dir() and paths['manifest'].is_file())
            # The fetched folder feeds prepare directly.
            self.assertEqual(len(prepare.discover_sources(paths['corpus'])), 1)

    def test_hf_source_plans_the_fetch_stage(self):
        from vibiomir import pipeline
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(output):
            pipeline.run(pipeline.parse_args(['--dry-run', '--source', 'hf', '--out', tmp,
                                              '--hf-revision', 'd' * 40]))
        text = output.getvalue()
        self.assertIn('[fetch]', text)
        self.assertIn('corpus_dddddddddddd', text)
        self.assertIn(str(Path('hf') / 'source' / 'query.parquet'), text)


class PipelineCliTests(unittest.TestCase):
    def test_profiles_fill_defaults_and_options_override(self):
        from vibiomir import pipeline
        local = pipeline.parse_args(['--dry-run'])
        self.assertEqual((local.gpus, local.reranker, local.translation_quantize), (1, 'bge-reranker-v2-m3', '4bit'))
        self.assertEqual((local.source, local.limit, local.out), (['nguyen'], 100000, 'work/run_local_100k'))
        self.assertEqual(pipeline.parse_args(['--limit', '0']).limit, 0)
        kaggle = pipeline.parse_args(['--profile', 'kaggle', '--reranker', 'bge-reranker-v2-m3'])
        self.assertEqual((kaggle.gpus, kaggle.reranker), (2, 'bge-reranker-v2-m3'))
        self.assertEqual(local.reranker, pipeline.parse_args(['--profile', 'kaggle']).reranker)
        self.assertEqual(local.hyde, [])
        self.assertEqual((kaggle.source, kaggle.limit), (['hf'], 0))

    def test_dry_run_plans_parallel_gpu_stages(self):
        from vibiomir import pipeline
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            pipeline.run(pipeline.parse_args(['--profile', 'kaggle', '--dry-run', '--out',
                                              str(Path(tempfile.gettempdir()) / 'vibiomir-dry')]))
        text = output.getvalue()
        for stage in ('[cards_dense_part1] GPU 1', '[subset_dense_merge]', '[retrieve_0] GPU 0',
                      '[retrieve_1] GPU 1', '[translate] GPU 1', '[submit]'):
            self.assertIn(stage, text)
        self.assertIn('--match-language', text)
        for gone in ('[chunk]', '[pilot]', 'submit_nowindow', 'qwen3-reranker'):
            self.assertNotIn(gone, text)
        self.assertEqual(json.loads(json.dumps(pipeline.WEIGHTS))['card'], 1.0)


if __name__ == '__main__':
    unittest.main()
