"""Exercise the notebook's upload boundary offline: no credentials or network calls."""
from contextlib import redirect_stdout
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / 'notebooks' / 'crawl_corpus_kaggle_hf_upload.ipynb'
FAKE_TOKEN = 'test-secret-must-never-appear-in-output'


class HTTPFailure(Exception):
    def __init__(self, status):
        super().__init__(FAKE_TOKEN)
        self.response = SimpleNamespace(status_code=status)


class NotebookUploadTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / 'tmp'
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.nb = json.loads(NOTEBOOK.read_text(encoding='utf-8'))
        source = ''.join(self.nb['cells'][-1]['source'])
        definitions = source.rsplit('\nhf_upload_result = ', 1)[0]
        self.env = {}
        exec(compile(definitions, str(NOTEBOOK), 'exec'), self.env)
        self.env.update(WORKDIR=self.work, DATASET_REVISION='test-revision')
        spec = importlib.util.spec_from_file_location('upload_postprocess_fixture', ROOT / 'scripts/notebook_postprocess.py')
        self.postprocess = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.postprocess)
        self.make_run(200582, 200682)

        self.api = Mock()
        self.api.create_commit.return_value = SimpleNamespace(
            oid='test-commit', commit_url='https://huggingface.co/test/commit/test-commit')
        hub = ModuleType('huggingface_hub')
        hub.HfApi = Mock(return_value=self.api)
        hub.CommitOperationAdd = lambda **kwargs: SimpleNamespace(**kwargs)
        secrets = ModuleType('kaggle_secrets')
        self.secret_client = Mock()
        self.secret_client.get_secret.return_value = FAKE_TOKEN
        secrets.UserSecretsClient = Mock(return_value=self.secret_client)
        self.hub = hub
        self.modules = {'huggingface_hub': hub, 'kaggle_secrets': secrets}

    def make_run(self, start, stop, *, pending=0, accepted=2):
        run = self.work / 'runs' / f'ids_{start}_{stop}_synced'
        run.mkdir(parents=True)
        manifest = {
            'id_from_inclusive': start, 'id_to_inclusive': stop,
            'dataset_revision': 'test-revision', 'source_sha256': 'test-source-sha',
            'selected': 101, 'completed': 101 - pending, 'pending': pending,
            'accepted': accepted, 'complete': pending == 0,
        }
        (run / 'notebook_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        (run / 'corpus.parquet').write_bytes(b'fixture: exporter-produced parquet')
        (run / 'corpus.jsonl').write_text('{"id": 200582, "text": "sample"}\n', encoding='utf-8')
        (self.work / f'{run.name}.zip').write_bytes(b'fixture: full archive')
        (self.work / f'{run.name}_diagnostics.zip').write_bytes(b'fixture: diagnostic archive')
        (run / 'postprocess_snapshot.py').write_bytes((ROOT / 'scripts/notebook_postprocess.py').read_bytes())
        (run / 'storage_snapshot.py').write_bytes((ROOT / 'scripts/corpus_storage.py').read_bytes())
        self.postprocess.write_json(run / 'manifest.json', {'source_sha256': 'test-source-sha'})
        (run / 'sample.jsonl').write_text('fixture source mapping\n', encoding='utf-8')
        (run / 'records').mkdir()
        self.postprocess.write_json(run / 'audit_summary.json', {
            'selected': 101, 'completed': 101, 'source_mapping_verified': True,
            'raw_and_text_hashes_verified': True,
        })
        self.postprocess.write_json(run / 'export_manifest.json', {
            'documents': accepted, 'accepted_source_ids_preserved': True,
            'parquet_round_trip_verified': True, 'jsonl_round_trip_verified': True,
            'files': {name: {'bytes': (run / name).stat().st_size,
                             'sha256': self.postprocess.file_hash(run / name)}
                      for name in ('corpus.parquet', 'corpus.jsonl')},
        })
        self.postprocess.write_json(run / 'postprocess_status.json', {
            'status': 'complete' if not pending else 'incomplete',
            'audit_passed': not pending, 'export_passed': not pending,
            'counts': {key: manifest[key] for key in ('selected', 'completed', 'pending', 'accepted')},
            'records_sha256': self.postprocess.records_hash(run),
            **{key: self.postprocess.file_hash(run / name) for name, key in (
                ('manifest.json', 'source_manifest_sha256'), ('sample.jsonl', 'sample_sha256'),
                ('audit_summary.json', 'audit_summary_sha256'), ('export_manifest.json', 'export_manifest_sha256'))},
        })
        self.env.update(RUN_DIR=run, ID_FROM=start, ID_TO=stop)
        return run

    def upload(self):
        self.output = io.StringIO()
        with patch.dict('sys.modules', self.modules), patch('subprocess.run') as installer, \
                patch('time.sleep'), redirect_stdout(self.output):
            try:
                return self.env['upload_current_run_to_hf']()
            finally:
                installer.assert_not_called()
                self.assertNotIn(FAKE_TOKEN, self.output.getvalue())

    def paths(self, call=-1):
        return {op.path_in_repo for op in self.api.create_commit.call_args_list[call].kwargs['operations']}

    def test_notebook_cells_compile(self):
        self.assertIn('tự upload Hugging Face', ''.join(self.nb['cells'][0]['source']))
        for i, cell in enumerate(self.nb['cells']):
            if cell['cell_type'] == 'code':
                compile(''.join(cell['source']), f'cell-{i}', 'exec')

    def test_complete_upload_paths_hashes_and_secret_handling(self):
        result = self.upload()
        run = self.env['RUN_DIR']
        self.assertEqual(result['status'], 'uploaded')
        self.assertEqual(self.paths(), {
            f'corpus/{run.name}.parquet',
            f'diagnostics/{run.name}_diagnostics.zip',
            f'manifests/{run.name}/notebook_manifest.json',
            f'manifests/{run.name}/upload_manifest.json',
        })
        self.secret_client.get_secret.assert_called_once_with('HF_TOKEN')
        self.hub.HfApi.assert_called_once_with(token=FAKE_TOKEN)
        self.assertEqual(self.api.create_commit.call_args.kwargs['repo_type'], 'dataset')
        self.assertEqual(self.api.create_commit.call_args.kwargs['repo_id'],
                         'AncientWings/AncientWings_R2AI_STAGE3_ds')
        manifest = json.loads((run / 'hf_upload_manifest.json').read_text(encoding='utf-8'))
        local_files = {op.path_in_repo: Path(op.path_or_fileobj)
                       for op in self.api.create_commit.call_args.kwargs['operations']}
        for item in manifest['files']:
            data = local_files[item['path_in_repo']].read_bytes()
            self.assertEqual(item['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(item['bytes'], len(data))
        self.assertEqual(manifest['counts']['accepted'], 2)
        for path in run.glob('*.json'):
            self.assertNotIn(FAKE_TOKEN, path.read_text(encoding='utf-8'))
        self.assertNotIn('token', self.env)

    def test_different_ranges_have_disjoint_remote_paths(self):
        self.upload()
        first = self.paths()
        self.make_run(200683, 220682)
        self.upload()
        self.assertFalse(first & self.paths())

    def test_pending_run_does_not_access_credentials_or_hub(self):
        self.make_run(1, 101, pending=1)
        self.assertEqual(self.upload()['status'], 'incomplete')
        self.secret_client.get_secret.assert_not_called()
        self.hub.HfApi.assert_not_called()

    def test_disabled_upload_does_not_access_credentials_or_hub(self):
        self.env['HF_UPLOAD_ENABLED'] = False
        self.assertEqual(self.upload()['status'], 'disabled')
        self.secret_client.get_secret.assert_not_called()
        self.hub.HfApi.assert_not_called()

    def test_legacy_complete_manifest_without_audit_proof_cannot_upload(self):
        (self.env['RUN_DIR'] / 'postprocess_status.json').unlink()
        with self.assertRaisesRegex(RuntimeError, 'audit/export'):
            self.upload()
        self.secret_client.get_secret.assert_not_called()
        self.hub.HfApi.assert_not_called()

    def test_failed_audit_with_no_pending_cannot_upload(self):
        self.postprocess.invalidate(self.env['RUN_DIR'], status='failed', failed_step='audit')
        with self.assertRaisesRegex(RuntimeError, 'Audit/export'):
            self.upload()
        self.secret_client.get_secret.assert_not_called()
        self.hub.HfApi.assert_not_called()

    def test_checkpoint_changed_after_audit_cannot_upload(self):
        self.postprocess.write_json(self.env['RUN_DIR'] / 'records/1.json', {'id': 1})
        with self.assertRaisesRegex(RuntimeError, 'Checkpoint'):
            self.upload()
        self.secret_client.get_secret.assert_not_called()
        self.hub.HfApi.assert_not_called()

    def test_corrupt_export_cannot_upload_even_when_jsonl_upload_is_disabled(self):
        self.env['HF_UPLOAD_JSONL'] = False
        (self.env['RUN_DIR'] / 'corpus.jsonl').write_bytes(b'corrupt export')
        with self.assertRaisesRegex(RuntimeError, 'corpus.jsonl'):
            self.upload()
        self.secret_client.get_secret.assert_not_called()
        self.hub.HfApi.assert_not_called()

    def test_manifest_from_other_range_is_rejected(self):
        self.env['ID_TO'] += 1
        with self.assertRaisesRegex(RuntimeError, 'khoảng ID'):
            self.upload()
        self.secret_client.get_secret.assert_not_called()

    def test_missing_archive_is_rejected_before_upload(self):
        self.env['HF_UPLOAD_ARCHIVE'] = True
        (self.work / f'{self.env["RUN_DIR"].name}.zip').unlink()
        with self.assertRaisesRegex(RuntimeError, 'Thiếu output'):
            self.upload()
        self.api.create_commit.assert_not_called()
        self.secret_client.get_secret.assert_not_called()

    def test_optional_artifacts_can_be_disabled(self):
        self.env.update(HF_UPLOAD_JSONL=False, HF_UPLOAD_ARCHIVE=False, HF_UPLOAD_DIAGNOSTICS=False)
        self.upload()
        self.assertEqual(len(self.paths()), 3)
        self.assertFalse(any(p.endswith(('.zip', '.jsonl')) for p in self.paths()))

    def test_default_upload_works_without_local_checkpoint_archive(self):
        (self.work / f'{self.env["RUN_DIR"].name}.zip').unlink()
        self.assertEqual(self.upload()['status'], 'uploaded')
        self.assertFalse(any(path.startswith('archives/') for path in self.paths()))

    def test_zero_accepted_never_uploads_stale_corpus(self):
        self.make_run(1, 101, accepted=0)
        self.upload()
        self.assertFalse(any(p.startswith(('corpus/', 'corpus_jsonl/')) for p in self.paths()))

    def test_missing_secret_reports_setup_without_leaking_it(self):
        self.secret_client.get_secret.side_effect = RuntimeError(FAKE_TOKEN)
        with self.assertRaises(RuntimeError) as caught:
            self.upload()
        self.assertIn('Kaggle Secret', str(caught.exception))
        self.assertNotIn(FAKE_TOKEN, str(caught.exception))
        self.hub.HfApi.assert_not_called()

    def test_access_error_reports_no_secret_and_makes_no_commit(self):
        self.api.repo_info.side_effect = HTTPFailure(403)
        with self.assertRaises(RuntimeError) as caught:
            self.upload()
        self.assertIn('HTTP 403', str(caught.exception))
        self.assertNotIn(FAKE_TOKEN, str(caught.exception))
        self.api.create_commit.assert_not_called()

    def test_original_runtime_message_is_visible_and_logged_without_secrets(self):
        jwt = 'eyJhbGciOiJIUzI1NiJ9.credential.signature'
        signed_secret = 'signed-query-credential'
        raw_error = (f'CAS service error: TLS handshake failed; token={FAKE_TOKEN}; '
                     f'Authorization: Bearer {jwt}; '
                     f'https://cas.example/upload?X-Amz-Signature={signed_secret}')
        self.api.create_commit.side_effect = RuntimeError(raw_error)
        with self.assertRaises(RuntimeError) as caught:
            self.upload()
        log_path = self.env['RUN_DIR'] / 'logs' / 'hf_upload_error.log'
        log = log_path.read_text(encoding='utf-8')
        for text in (str(caught.exception), self.output.getvalue(), log):
            self.assertIn('CAS service error: TLS handshake failed', text)
            for secret in (FAKE_TOKEN, jwt, signed_secret):
                self.assertNotIn(secret, text)
        self.assertIn('"stage": "create_commit"', log)
        self.assertIn('"attempt": 3', log)
        self.assertIn('"sdk_versions"', log)
        self.assertIn('Traceback (most recent call last)', log)
        self.assertNotIn('Upload lỗi mạng/server', self.output.getvalue())

    def test_http_status_in_runtime_message_is_reported_and_not_retried(self):
        self.api.create_commit.side_effect = RuntimeError(
            'Data processing error: CAS service error: HTTP status client error (401 Unauthorized)')
        with self.assertRaises(RuntimeError) as caught:
            self.upload()
        self.assertIn('HTTP 401', str(caught.exception))
        self.assertIn('401 Unauthorized', str(caught.exception))
        self.assertEqual(self.api.create_commit.call_count, 1)

    def test_nested_http_error_is_reported_even_if_wrapper_suppresses_context(self):
        nested = HTTPFailure(403)
        wrapped = RuntimeError('Upload worker failed')
        wrapped.__cause__ = nested
        wrapped.__suppress_context__ = True
        self.api.create_commit.side_effect = wrapped
        with self.assertRaises(RuntimeError) as caught:
            self.upload()
        self.assertIn('HTTP 403', str(caught.exception))
        self.assertIn('Upload worker failed', str(caught.exception))
        self.assertIn('Caused by: HTTPFailure', str(caught.exception))
        self.assertNotIn(FAKE_TOKEN, str(caught.exception))
        self.assertEqual(self.api.create_commit.call_count, 1)

    def test_repo_access_root_message_is_preserved(self):
        self.api.repo_info.side_effect = RuntimeError('DNS resolution failed for huggingface.co')
        with self.assertRaises(RuntimeError) as caught:
            self.upload()
        self.assertIn('DNS resolution failed', str(caught.exception))
        log = (self.env['RUN_DIR'] / 'logs' / 'hf_upload_error.log').read_text(encoding='utf-8')
        self.assertIn('"stage": "repo_info"', log)
        self.assertIn('DNS resolution failed', log)
        self.api.create_commit.assert_not_called()

    def test_diagnostic_file_write_failure_does_not_hide_upload_error(self):
        self.api.create_commit.side_effect = RuntimeError('upload protocol mismatch')
        with patch('traceback.format_exception', side_effect=OSError('log device unavailable')):
            with self.assertRaises(RuntimeError) as caught:
                self.upload()
        self.assertIn('upload protocol mismatch', str(caught.exception))
        self.assertIn('Không ghi được file log', self.output.getvalue())

    def test_transient_failure_retries_with_fresh_operations(self):
        first_operations = []

        def commit(**kwargs):
            if not first_operations:
                first_operations.extend(kwargs['operations'])
                for op in first_operations:
                    op.path_or_fileobj = b''  # Mimic SDK mutation after pre-upload.
                raise HTTPFailure(503)
            self.assertTrue(all(isinstance(op.path_or_fileobj, str) for op in kwargs['operations']))
            return SimpleNamespace(oid='retried', commit_url='https://huggingface.co/test/commit/retried')

        self.api.create_commit.side_effect = commit
        self.assertEqual(self.upload()['commit_oid'], 'retried')
        self.assertEqual(self.api.create_commit.call_count, 2)

    def test_write_denied_does_not_retry_or_record_success(self):
        self.api.create_commit.side_effect = HTTPFailure(403)
        with self.assertRaises(RuntimeError) as caught:
            self.upload()
        self.assertIn('HTTP 403', str(caught.exception))
        self.assertNotIn(FAKE_TOKEN, str(caught.exception))
        self.assertEqual(self.api.create_commit.call_count, 1)
        self.assertFalse((self.env['RUN_DIR'] / 'hf_upload_result.json').exists())
        self.assertTrue((self.env['RUN_DIR'] / 'corpus.parquet').is_file())


if __name__ == '__main__':
    unittest.main()
