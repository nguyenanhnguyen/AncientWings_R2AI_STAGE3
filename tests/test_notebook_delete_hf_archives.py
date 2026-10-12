"""Exercise archive cleanup offline; never connect to or delete anything on the Hub."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


NOTEBOOK = Path(__file__).resolve().parents[1] / 'notebooks/delete_hf_archives.ipynb'
TOKEN = 'test-secret-must-not-appear'


class FakeRepoFile(SimpleNamespace):
    pass


class ArchiveCleanupTests(unittest.TestCase):
    def setUp(self):
        notebook = json.loads(NOTEBOOK.read_text(encoding='utf-8'))
        self.assertEqual(len(notebook['cells']), 1)
        source = ''.join(notebook['cells'][0]['source'])
        compile(source, str(NOTEBOOK), 'exec')
        self.env = {}
        exec(source.rsplit('\nhf_archives_cleanup_result = ', 1)[0], self.env)
        self.tree = [
            FakeRepoFile(path='archives/run.zip', blob_id='pointer', lfs=SimpleNamespace(sha256='archive-oid')),
            FakeRepoFile(path='corpus/run.parquet', blob_id='corpus-blob', lfs=SimpleNamespace(sha256='corpus-oid')),
            FakeRepoFile(path='teach/data.jsonl', blob_id='teach-blob', lfs=None),
            FakeRepoFile(path='archives_backup/keep.zip', blob_id='backup-blob', lfs=SimpleNamespace(sha256='backup-oid')),
            SimpleNamespace(path='archives', tree_id='folder'),
        ]
        self.lfs = [
            SimpleNamespace(filename='archives/run.zip', file_oid='archive-oid', size=100),
            SimpleNamespace(filename='archives/old.zip', file_oid='historical-oid', size=200),
            SimpleNamespace(filename='corpus/run.parquet', file_oid='corpus-oid', size=30),
            SimpleNamespace(filename='archives_backup/keep.zip', file_oid='backup-oid', size=50),
        ]
        self.api = Mock()
        self.api.repo_info.return_value = SimpleNamespace(sha='head')
        self.api.list_repo_tree.side_effect = lambda **kw: iter(self.tree)
        self.api.list_lfs_files.side_effect = lambda **kw: iter(self.lfs)

        def remove_folder(**kw):
            self.tree = [item for item in self.tree if not item.path.startswith('archives/')]
            return SimpleNamespace(commit_url='https://huggingface.co/test/commit/deletion')

        def purge(**kw):
            deleted = {item.file_oid for item in kw['lfs_files']}
            self.lfs = [item for item in self.lfs if item.file_oid not in deleted]

        self.api.delete_folder.side_effect = remove_folder
        self.api.permanently_delete_lfs_files.side_effect = purge
        hub = ModuleType('huggingface_hub')
        hub.HfApi = Mock(return_value=self.api)
        hub.RepoFile = FakeRepoFile
        hub.get_token = lambda: TOKEN
        self.hub = hub
        self.modules = {'huggingface_hub': hub}

    def cleanup(self):
        self.output = io.StringIO()
        with patch.dict('sys.modules', self.modules), patch.dict('os.environ', {}, clear=True), \
                patch('subprocess.run') as installer, redirect_stdout(self.output):
            try:
                return self.env['delete_hf_archives']()
            finally:
                installer.assert_not_called()
                self.assertNotIn(TOKEN, self.output.getvalue())

    def test_only_archives_are_deleted_including_historical_lfs(self):
        result = self.cleanup()
        deletion = self.api.delete_folder.call_args.kwargs
        self.assertEqual(deletion['path_in_repo'], 'archives')
        self.assertEqual(deletion['repo_id'], 'AncientWings/AncientWings_R2AI_STAGE3_ds')
        self.assertEqual(deletion['repo_type'], 'dataset')
        self.assertEqual(deletion['revision'], 'main')
        self.assertEqual(deletion['parent_commit'], 'head')
        purge = self.api.permanently_delete_lfs_files.call_args.kwargs
        self.assertEqual({item.file_oid for item in purge['lfs_files']}, {'archive-oid', 'historical-oid'})
        self.assertTrue(purge['rewrite_history'])
        self.assertEqual(purge['repo_id'], deletion['repo_id'])
        self.assertEqual(purge['repo_type'], 'dataset')
        self.assertEqual(result['removed_paths'], 1)
        self.assertEqual(result['archive_bytes_targeted'], 300)
        self.assertFalse(self.env['HF_UPLOAD_ARCHIVE'])
        self.api.super_squash_history.assert_not_called()

    def test_shared_blob_outside_archives_blocks_all_mutations(self):
        self.tree.append(FakeRepoFile(path='teach/shared.zip', blob_id='shared',
                                     lfs=SimpleNamespace(sha256='archive-oid')))
        with self.assertRaisesRegex(RuntimeError, 'dùng chung'):
            self.cleanup()
        self.api.delete_folder.assert_not_called()
        self.api.permanently_delete_lfs_files.assert_not_called()

    def test_lfs_alias_outside_current_main_also_blocks_mutations(self):
        self.lfs.append(SimpleNamespace(filename='other/old.zip', file_oid='historical-oid', size=200))
        with self.assertRaisesRegex(RuntimeError, 'dùng chung'):
            self.cleanup()
        self.api.delete_folder.assert_not_called()
        self.api.permanently_delete_lfs_files.assert_not_called()

    def test_repeated_cleanup_is_a_noop(self):
        self.cleanup()
        self.api.reset_mock()
        result = self.cleanup()
        self.assertEqual(result['removed_paths'], 0)
        self.assertEqual(result['purged_lfs_objects'], 0)
        self.api.delete_folder.assert_not_called()
        self.api.permanently_delete_lfs_files.assert_not_called()

    def test_historical_lfs_is_purged_when_folder_was_already_deleted(self):
        self.tree = [item for item in self.tree if not item.path.startswith('archives/')]
        self.cleanup()
        self.api.delete_folder.assert_not_called()
        self.api.permanently_delete_lfs_files.assert_called_once()

    def test_history_purge_can_be_disabled(self):
        self.env['HF_ARCHIVES_PURGE_LFS'] = False
        self.cleanup()
        self.api.delete_folder.assert_called_once()
        self.api.list_lfs_files.assert_not_called()
        self.api.permanently_delete_lfs_files.assert_not_called()

    def test_failed_folder_commit_does_not_purge_lfs(self):
        self.api.delete_folder.side_effect = RuntimeError(TOKEN)
        with self.assertRaisesRegex(RuntimeError, 'delete_folder') as caught:
            self.cleanup()
        self.assertNotIn(TOKEN, str(caught.exception))
        self.api.permanently_delete_lfs_files.assert_not_called()

    def test_missing_token_makes_no_remote_calls(self):
        self.hub.get_token = lambda: None
        secrets = ModuleType('kaggle_secrets')
        secrets.UserSecretsClient = Mock()
        secrets.UserSecretsClient.return_value.get_secret.side_effect = RuntimeError(TOKEN)
        self.modules['kaggle_secrets'] = secrets
        with self.assertRaisesRegex(RuntimeError, 'Kaggle Secret') as caught:
            self.cleanup()
        self.assertNotIn(TOKEN, str(caught.exception))
        self.hub.HfApi.assert_not_called()

    def test_unrelated_content_change_is_reported(self):
        def purge_with_concurrent_change(**kw):
            self.tree.append(FakeRepoFile(path='teach/new.jsonl', blob_id='new', lfs=None))
        self.api.permanently_delete_lfs_files.side_effect = purge_with_concurrent_change
        with self.assertRaisesRegex(RuntimeError, 'thay đổi trong lúc dọn'):
            self.cleanup()


if __name__ == '__main__':
    unittest.main()
