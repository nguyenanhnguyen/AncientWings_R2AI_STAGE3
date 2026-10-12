"""Qwen inference semantics with tiny real Transformers models; no weight downloads."""
import contextlib
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np
import torch
from transformers import BatchEncoding, Qwen3Config, Qwen3Model, Qwen3ForCausalLM

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.append(str(ROOT/'scripts'))
from vibiomir.index.embedding import TransformerEncoder, ENCODERS
from vibiomir.retrieval.rerank import CrossEncoderReranker, RERANKERS
from vibiomir.teach.models import load_backbone
from vibiomir.pipeline import parse_args, run


def tiny_config():
    return Qwen3Config(vocab_size=128, hidden_size=32, intermediate_size=64,
                       num_hidden_layers=1, num_attention_heads=4, num_key_value_heads=2,
                       head_dim=8, max_position_embeddings=128, pad_token_id=0,
                       use_cache=False, attn_implementation='sdpa')


class QwenKaggleTests(unittest.TestCase):
    def test_local_stays_bge_kaggle_selects_only_one_larger_scorer(self):
        local, kaggle = parse_args([]), parse_args(['--profile', 'kaggle', '--dry-run'])
        self.assertEqual((local.encoder, local.reranker, local.encoder_batch, local.rerank_batch),
                         ('bge-m3', 'bge-reranker-v2-m3', 8, 2))
        self.assertEqual((kaggle.encoder, kaggle.reranker), ('qwen3-embedding-4b', 'qwen3-reranker-4b'))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            run(kaggle)
        plan = out.getvalue()
        self.assertEqual(plan.count('--reranker qwen3-reranker-4b'), 2)  # disjoint query shards
        for absent in ('--extra-reranker', '[translate]', ' teach ', ' feedback '):
            self.assertNotIn(absent, plan)

    def test_pinned_revision_reaches_tokenizer_and_model_for_both_roles(self):
        for cls, name, registry, module in (
                (TransformerEncoder, 'qwen3-embedding-4b', ENCODERS, 'vibiomir.index.embedding'),
                (CrossEncoderReranker, 'qwen3-reranker-4b', RERANKERS, 'vibiomir.retrieval.rerank')):
            tokenizer = Mock()
            tokenizer.encode.return_value = [1]
            model = Mock()
            model.config = types.SimpleNamespace(hidden_size=2560, use_cache=True)
            with patch('transformers.AutoTokenizer.from_pretrained', return_value=tokenizer) as tok, \
                    patch(module+'.load_backbone', return_value=model) as load:
                owner = cls(name, device='cuda:0')
            self.assertEqual(tok.call_args.kwargs['revision'], registry[name]['revision'])
            passed = load.call_args
            revision = passed.kwargs.get('revision') if len(passed.args) < 5 else passed.args[4]
            self.assertEqual(revision, registry[name]['revision'])
            self.assertIs(passed.args[3], torch.float16)
            self.assertEqual(passed.kwargs['attn_implementation'], 'sdpa')
            self.assertEqual(tokenizer.padding_side, 'left')
            self.assertFalse(owner.model.config.use_cache)

    def test_direct_gpu_loading_does_not_stage_full_model_on_cpu(self):
        factory = Mock()
        load_backbone(factory, ENCODERS['qwen3-embedding-4b'], 'cuda:0', torch.float16)
        kwargs = factory.from_pretrained.call_args.kwargs
        self.assertEqual(kwargs['device_map'], {'': 'cuda:0'})
        self.assertTrue(kwargs['low_cpu_mem_usage'])
        self.assertNotIn('quantization_config', kwargs)
        factory.from_pretrained.return_value.to.assert_not_called()

    def test_last_token_pooling_is_padding_invariant_with_real_qwen(self):
        model = Qwen3Model(tiny_config()).eval()
        encoder = TransformerEncoder.__new__(TransformerEncoder)
        encoder.config = {'pooling': 'last'}
        with torch.inference_mode():
            plain_mask = torch.tensor([[1, 1, 1]])
            plain = model(input_ids=torch.tensor([[8, 9, 10]]), attention_mask=plain_mask)
            padded_mask = torch.tensor([[0, 0, 1, 1, 1]])
            padded = model(input_ids=torch.tensor([[0, 0, 8, 9, 10]]), attention_mask=padded_mask)
            torch.testing.assert_close(encoder._pool(plain, plain_mask), encoder._pool(padded, padded_mask),
                                       rtol=1e-4, atol=1e-5)

    def test_query_instruction_and_documents_are_encoded_differently(self):
        encoder = TransformerEncoder.__new__(TransformerEncoder)
        encoder.config = dict(ENCODERS['qwen3-embedding-4b'])
        encoder.torch, encoder.device, encoder.dim = torch, 'cpu', 32
        encoder.model = Qwen3Model(tiny_config()).eval()
        seen = []
        def tokenize(texts, **kwargs):
            seen.extend(texts)
            return BatchEncoding({'input_ids': torch.tensor([[8, 9, 10]] * len(texts)),
                                  'attention_mask': torch.ones(len(texts), 3, dtype=torch.long)})
        encoder.tokenizer = tokenize
        q = encoder.encode(['question'], kind='query', batch_size=1)
        d = encoder.encode(['document'], kind='doc', batch_size=1)
        self.assertTrue(seen[0].startswith('Instruct: '))
        self.assertTrue(seen[0].endswith('\nQuery: question'))
        self.assertEqual(seen[1], 'document')
        np.testing.assert_allclose(np.linalg.norm(q, axis=1), [1], atol=1e-6)
        self.assertTrue(np.isfinite(d).all())

    def test_final_token_yes_no_matches_full_logits_without_generation(self):
        model = Qwen3ForCausalLM(tiny_config()).eval()
        scorer = CrossEncoderReranker.__new__(CrossEncoderReranker)
        scorer.model, scorer.torch = model, torch
        scorer.config = {'kind': 'causal-yes-no'}
        scorer.no_id, scorer.yes_id = 6, 7
        inputs = {'input_ids': torch.tensor([[0, 8, 9, 10], [8, 9, 10, 11]]),
                  'attention_mask': torch.tensor([[0, 1, 1, 1], [1, 1, 1, 1]])}
        with torch.inference_mode(), patch.object(model, 'generate', side_effect=AssertionError('No generation')):
            expected = model(**inputs, use_cache=False).logits[:, -1, [6, 7]].float().softmax(1)[:, 1]
            actual = scorer._logits(inputs)
        torch.testing.assert_close(actual, expected)
        self.assertTrue(torch.isfinite(actual).all())

    def test_notebook_explicitly_passes_models_and_keeps_weights_out_of_output(self):
        import build_notebooks as b
        self.assertIn("ENCODER = 'qwen3-embedding-4b'", b.CONFIG)
        self.assertIn("RERANKER = 'qwen3-reranker-4b'", b.CONFIG)
        self.assertIn("'--encoder', ENCODER, '--reranker', RERANKER", b.RUN_CELL)
        self.assertIn('/kaggle/temp/vibiomir_hf_cache', b.CONFIG)
        self.assertIn('run_qwen4b_', b.CONFIG)
        self.assertIn('accelerate>=1.6', b.INSTALL)


if __name__ == '__main__':
    unittest.main()
