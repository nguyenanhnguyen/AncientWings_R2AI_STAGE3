import copy
import unittest

from vibiomir.corpus.chunk import contextual_embedding_texts, retrieval_text


class CharacterTokenizer:
    def __call__(self, text, **kwargs):
        return {'offset_mapping': [(i, i+1) for i in range(len(text))]}

    def encode(self, text, **kwargs):
        return [0] + list(text) + [1]


class ContextualEmbeddingTests(unittest.TestCase):
    def test_context_budget_mapping_and_original_spans(self):
        first = dict(doc_id=1, chunk_order=0, chunk_id='1:0', char_start=0,
                     char_end=160, text='A'*80+'B'*80, title='Title')
        second = dict(doc_id=1, chunk_order=1, chunk_id='1:1', char_start=140,
                      char_end=300, text='B'*20+'C'*140, title='Title')
        unrelated = dict(doc_id=2, chunk_order=0, chunk_id='2:0', char_start=0,
                         char_end=20, text='Z'*20, title='Other')
        rows = [second, unrelated, first]
        original = copy.deepcopy(rows)
        texts, report = contextual_embedding_texts(rows, CharacterTokenizer(), 240)
        self.assertEqual(rows, original)
        self.assertTrue(texts[0].endswith(retrieval_text(second)))
        self.assertIn('A', texts[0])
        self.assertEqual(texts[1], retrieval_text(unrelated))
        self.assertEqual(texts[2], retrieval_text(first))
        self.assertTrue(all(len(t)+2 <= 240 for t in texts))
        self.assertEqual(report['augmented_chunks'], 1)

        adjacent, details = contextual_embedding_texts(rows, CharacterTokenizer(), 240,
                                                       include_lead=False)
        self.assertNotIn('A', adjacent[0])
        self.assertTrue(adjacent[0].endswith(retrieval_text(second)))
        self.assertEqual(adjacent[1], retrieval_text(unrelated))
        self.assertEqual(details['lead_tokens'], 0)
        self.assertEqual(rows, original)

    def test_no_space_keeps_body_and_oversize_fails(self):
        rows = [dict(doc_id=1, chunk_order=i, chunk_id=f'1:{i}', char_start=i*100,
                     text=letter*100, title='T') for i, letter in enumerate('AB')]
        texts, _ = contextual_embedding_texts(rows, CharacterTokenizer(), 104)
        self.assertEqual(texts, [retrieval_text(r) for r in rows])
        with self.assertRaises(ValueError):
            contextual_embedding_texts(rows, CharacterTokenizer(), 100)


if __name__ == '__main__':
    unittest.main()
