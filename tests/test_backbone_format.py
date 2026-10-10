"""Regression coverage for loading both bin-only and safetensors checkpoints."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from vibiomir.teach.models import load_backbone


class BackboneFormatTests(unittest.TestCase):
    def test_official_bin_only_checkpoint_is_allowed(self):
        model = Mock()
        model.to.return_value = model
        model.eval.return_value = model
        def load(name, **kwargs):
            if kwargs.get('use_safetensors') is True:
                raise OSError('No model.safetensors in this repository')
            self.assertEqual(name, 'BAAI/bge-m3')
            self.assertEqual(kwargs['revision'], 'pinned')
            return model
        factory = Mock()
        factory.from_pretrained.side_effect = load
        self.assertIs(load_backbone(factory, {'hf_id': 'BAAI/bge-m3'}, 'cpu',
                                    'float32', revision='pinned'), model)
        model.to.assert_called_once_with('cpu')

    def test_explicit_format_requirement_is_not_overridden(self):
        factory = Mock()
        load_backbone(factory, {'hf_id': 'test/model'}, 'cpu', 'float32', use_safetensors=True)
        self.assertIs(factory.from_pretrained.call_args.kwargs['use_safetensors'], True)

    def test_safetensors_model_uses_auto_selection(self):
        factory = Mock()
        load_backbone(factory, {'hf_id': 'test/safetensors'}, 'cpu', 'float32')
        self.assertIsNone(factory.from_pretrained.call_args.kwargs['use_safetensors'])


if __name__ == '__main__':
    unittest.main()
