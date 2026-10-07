"""Block T without a GPU or a download: data plumbing, parsing, resumable logs and the losses.

The teacher and the students themselves need Kaggle; what is checked here is everything around
them that would otherwise only fail hours into a session.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from vibiomir.common import storage  # noqa: E402
from vibiomir.corpus import chunk as chunking  # noqa: E402
from vibiomir.index import build as index_cli  # noqa: E402
from vibiomir.teach import mine, models, sample, store, train  # noqa: E402

from test_pipeline import write_fixture  # noqa: E402

PASSAGE = ('Sốt xuất huyết\nTrẻ bị sốt xuất huyết cần uống nhiều nước, dùng paracetamol hạ sốt '
           'và tuyệt đối không dùng aspirin vì làm tăng nguy cơ chảy máu.')


def teacher_json(**overrides):
    data = {'usable': True, 'query': 'Con em 5 tuổi bị sốt xuất huyết thì có uống aspirin được không ạ?',
            'evidence': 'tuyệt đối không dùng aspirin',
            'query_en': 'My 5 year old child has dengue fever, can he take aspirin?',
            'query_zh': '我5岁的孩子得了登革热，可以吃阿司匹林吗？'}
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


class ParseTests(unittest.TestCase):
    def test_accepts_grounded_query_and_strips_thinking(self):
        record, reason = models.parse_generation('<think>x</think>\n' + teacher_json(), PASSAGE)
        self.assertIsNone(reason)
        self.assertEqual(record['evidence'], 'tuyệt đối không dùng aspirin')
        self.assertTrue(record['query_zh'])

    def test_rejects_evidence_not_in_passage(self):
        _record, reason = models.parse_generation(teacher_json(evidence='dùng ibuprofen'), PASSAGE)
        self.assertEqual(reason, 'evidence_not_in_passage')

    def test_rejects_unusable_and_non_vietnamese_and_garbage(self):
        self.assertEqual(models.parse_generation('{"usable": false}', PASSAGE)[1], 'not_usable')
        self.assertEqual(models.parse_generation(
            teacher_json(query='Can a child with dengue take aspirin at all?'), PASSAGE)[1],
            'query_not_vietnamese')
        self.assertEqual(models.parse_generation('no json here', PASSAGE)[1], 'no_json')

    def test_bad_translation_is_dropped_but_query_kept(self):
        record, reason = models.parse_generation(
            teacher_json(query_en='', query_zh='Con 5 tuổi'), PASSAGE)
        self.assertIsNone(reason)
        self.assertIsNone(record['query_en'])
        self.assertIsNone(record['query_zh'])


class StoreTests(unittest.TestCase):
    def test_torn_last_line_is_dropped_and_keys_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = store.open_log(temporary, 'generated', 0, 2, 'chunk_id')
            log.append([{'chunk_id': 'a'}, {'chunk_id': 'b'}])
            with log.path.open('a', encoding='utf-8') as stream:
                stream.write('{"chunk_id": "c", "que')
            again = store.open_log(temporary, 'generated', 0, 2, 'chunk_id')
            self.assertEqual(again.done, {'a', 'b'})
            again.append([{'chunk_id': 'c'}])
            self.assertEqual([row['chunk_id'] for row in store.read_stage(temporary, 'generated')],
                             ['a', 'b', 'c'])

    def test_shard_assignment_is_stable(self):
        self.assertEqual(store.shard_of('123:4', 4), store.shard_of('123:4', 4))
        self.assertEqual({store.shard_of(f'{i}:0', 3) for i in range(60)}, {0, 1, 2})


class FlowTests(unittest.TestCase):
    def test_sample_then_mine_with_fake_teacher_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = write_fixture(root)
            chunking.build(argparse.Namespace(
                corpus=[str(fixture['corpus'])], out=str(root / 'chunks'), target_tokens=40,
                overlap_tokens=10, max_tokens=80, min_tokens=8, text_field=None, status='ok'))
            chunks_file = root / 'chunks' / 'chunks.parquet'
            index_cli.build_all(argparse.Namespace(
                chunks=str(chunks_file), out=str(root / 'index'), k1=1.5, b=0.75,
                encoder='hash', device='cpu', batch_size=4, shard=8, fp32=True, faiss=False,
                faiss_lists=0))
            teach = root / 'teach'
            summary = sample.build(argparse.Namespace(
                chunks=str(chunks_file), out=str(teach), target=10, shards=2, min_tokens=8,
                languages=None, dev_permille=500, seed=1))
            seeds = storage.read_jsonl(teach / 'seeds.jsonl')
            self.assertEqual(summary['seeds'], len(seeds))
            self.assertEqual(len({row['doc_id'] for row in seeds}), len(seeds))
            for shard in range(2):
                log = store.open_log(teach, 'generated', shard, 2, 'chunk_id')
                log.append([{'chunk_id': row['chunk_id'], 'doc_id': row['doc_id'],
                             'split': row['split'], 'error': None,
                             'query': row['passage'][:60], 'query_en': None, 'query_zh': None}
                            for row in seeds if row['shard'] == shard])
            report = mine.build(argparse.Namespace(
                teach=str(teach), chunks=str(chunks_file), index=str(root / 'index'),
                extra_index=[], shards=2, top_k=20, hard=3, tail=1, tail_from=4, device='cpu',
                search_device='cpu', batch_size=4, seed=1))
            groups = storage.read_jsonl(teach / 'groups.jsonl')
            self.assertEqual(report['groups'], len(seeds))
            doc_of = {row['chunk_id']: row['doc_id']
                      for row in storage.read_parquet(chunks_file, columns=['chunk_id', 'doc_id'])}
            for group in groups:
                own = doc_of[group['positive']]
                self.assertTrue(all(doc_of[cid] != own for cid in group['negatives']))
            # A query that is a slice of its own chunk is easy: the fused retriever must find it.
            self.assertGreater(report['retriever_on_synthetic_queries']['fused']['recall@10'], 0.5)

            judged = store.open_log(teach, 'judged', 0, 1, 'qid')
            judged.append([{'qid': group['qid'],
                            'scores': {group['positive']: 0.9 if i else 0.2,
                                       **{cid: 0.1 for cid in group['negatives']}}}
                           for i, group in enumerate(groups)])
            kept, texts, dropped = train.load_groups(teach, chunks_file)
            self.assertEqual(dropped, 1)
            self.assertEqual(len(kept), len(groups) - 1)
            self.assertTrue(all(group['items'][0]['label'] for group in kept))
            self.assertTrue(all(item['chunk_id'] in texts for g in kept for item in g['items']))


class LossTests(unittest.TestCase):
    def test_reranker_loss_prefers_the_teacher_order(self):
        import torch

        teacher = torch.tensor([[0.95, 0.10, 0.05]])
        good = train.reranker_loss(torch.tensor([[4.0, -2.0, -3.0]]), teacher)
        bad = train.reranker_loss(torch.tensor([[-3.0, 4.0, -2.0]]), teacher)
        self.assertLess(float(good), float(bad))

    def test_embedding_loss_masks_teacher_positives_and_decreases_when_aligned(self):
        import torch
        import torch.nn.functional as F

        queries = F.normalize(torch.tensor([[1.0, 0.0], [0.0, 1.0]]), dim=-1)
        aligned = F.normalize(torch.tensor([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0], [0.1, 0.9]]), dim=-1)
        labels = torch.tensor([[True, True], [True, False]])
        probs = torch.tensor([[0.9, 0.85], [0.9, 0.05]])
        good = train.embedding_loss(queries, aligned, 2, labels, probs)
        crossed = train.embedding_loss(queries, aligned.flip(0), 2, labels, probs)
        self.assertTrue(torch.isfinite(good))
        self.assertLess(float(good), float(crossed))

    def test_pick_items_keeps_positive_first(self):
        import random

        group = {'items': [{'chunk_id': 'p', 'teacher': 0.9, 'label': True},
                           *[{'chunk_id': str(i), 'teacher': i / 20, 'label': False}
                             for i in range(10)]]}
        picked = train.pick_items(group, 5, random.Random(0))
        self.assertEqual(picked[0]['chunk_id'], 'p')
        self.assertEqual(len(picked), 5)
        self.assertIn('9', [item['chunk_id'] for item in picked])


class StudentRegistryTests(unittest.TestCase):
    def test_finished_student_is_discovered_with_adapter_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / 'reranker-4b'
            folder.mkdir()
            (folder / 'adapter_model.safetensors').write_bytes(b'weights')
            storage.write_json(folder / models.STUDENT_FILE, {
                'task': 'reranker', 'size': '4b', 'base': 'Qwen/Qwen3-Reranker-4B',
                'quantize': 'none', 'config': {'kind': 'causal-yes-no', 'max_length': 640}})
            found = models.discover_students('reranker', temporary)
            self.assertIn('student:reranker-4b', found)
            self.assertEqual(found['student:reranker-4b']['hf_id'], 'Qwen/Qwen3-Reranker-4B')
            self.assertEqual(models.discover_students('embedding', temporary), {})
            (folder / 'adapter_model.safetensors').write_bytes(b'other')
            again = models.discover_students('reranker', temporary)
            self.assertNotEqual(found['student:reranker-4b']['adapter_sha'],
                                again['student:reranker-4b']['adapter_sha'])


if __name__ == '__main__':
    unittest.main()
