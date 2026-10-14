"""The local HF path must stop fetching shards once a bounded sample is complete."""
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from src.vibiomir.common import storage
from src.vibiomir.corpus import hf_snapshot


@contextmanager
def scratch_directory():
    root = Path(__file__).resolve().parents[1] / 'work' / 'hf_snapshot_tests'
    root.mkdir(parents=True, exist_ok=True)
    path = root / uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        if not path.resolve().is_relative_to(root.resolve()):
            raise RuntimeError('Refusing to clean a path outside the test scratch directory')
        shutil.rmtree(path)


class BoundedSnapshotTests(unittest.TestCase):
    def test_reads_only_needed_remote_shards_and_keeps_official_ids(self):
        with scratch_directory() as root:
            out = root / 'snapshot'
            out.mkdir()
            links = out / hf_snapshot.LINKS_NAME
            query = out / hf_snapshot.QUERIES_NAME
            pq.write_table(pa.Table.from_pylist([
                {'id': number, 'url': f'https://example.org/{number}'}
                for number in range(1, 7)]), links)
            query.write_bytes(b'fixture')
            sources = {}
            for number, letter in enumerate('abc'):
                path = root / f'{letter}.parquet'
                first = number * 2 + 1
                pq.write_table(pa.Table.from_pylist([
                    {'id': doc_id, 'url': f'https://example.org/{doc_id}',
                     'text': f'Bai viet suc khoe {doc_id}', 'lang': 'vi'}
                    for doc_id in (first, first + 1)]), path)
                sources[f'corpus/{letter}.parquet'] = path

            class FakeApi:
                def __init__(self, **_kwargs):
                    pass

                def dataset_info(self, *_args, **_kwargs):
                    return SimpleNamespace(sha='a' * 40)

                def list_repo_files(self, **_kwargs):
                    return list(sources)

            class FakeFs:
                opened = []

                def __init__(self, **_kwargs):
                    pass

                def open(self, path, *_args, **_kwargs):
                    name = 'corpus/' + path.rsplit('/corpus/', 1)[1]
                    self.opened.append(name)
                    return sources[name].open('rb')

            args = SimpleNamespace(repo='team/private', revision='main', limit=3,
                                   seed=13, sample_mode='bounded', out=out)
            with patch('huggingface_hub.HfApi', FakeApi), \
                 patch('huggingface_hub.HfFileSystem', FakeFs), \
                 patch('huggingface_hub.get_token', return_value='test-token'), \
                 patch('huggingface_hub.hf_hub_download') as download, \
                 patch.object(hf_snapshot, 'LINKS_SHA256', storage.sha256_file(links)), \
                 patch.object(hf_snapshot, 'QUERIES_SHA256', storage.sha256_file(query)):
                report = hf_snapshot.build(args)
                second = hf_snapshot.build(args)
                download.assert_not_called()
                capped = root / 'capped'
                capped.mkdir()
                (capped / links.name).write_bytes(links.read_bytes())
                (capped / query.name).write_bytes(query.read_bytes())
                capped_args = SimpleNamespace(**{**vars(args), 'out': capped, 'max_shards': 1})
                with self.assertRaisesRegex(ValueError, 'Increase --max-shards'):
                    hf_snapshot.build(capped_args)
            self.assertEqual(report['selected'], 3)
            self.assertEqual(report['counts']['files_read'], 2)
            self.assertEqual(len(FakeFs.opened), 3)
            self.assertFalse((capped / 'input_vi.parquet').exists())
            self.assertFalse((capped / 'input_vi.partial.parquet').exists())
            self.assertEqual(second, report)
            rows = pq.read_table(out / 'input_vi.parquet').to_pylist()
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(row['url'] == f"https://example.org/{row['id']}" for row in rows))


if __name__ == '__main__':
    unittest.main()
