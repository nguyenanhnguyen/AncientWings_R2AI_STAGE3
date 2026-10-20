"""R2: sharing violations, crash boundaries, cooldown and resume without another GET."""
from contextlib import redirect_stdout
import ctypes
import errno
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import cnkang_transport as transport
from test_cnkang_v6_check import page, response, URL

storage = transport.STORAGE


def build_backup(out):
    import hashlib
    from types import SimpleNamespace
    import corpus_checkpoint
    sample_path = out / 'sample.jsonl'
    sample_path.write_text(json.dumps({'id': 1, 'url': URL}) + '\n', encoding='utf-8')
    storage.write_json(out / 'manifest.json', {
        'selected': 1, 'sample_sha256': hashlib.sha256(sample_path.read_bytes()).hexdigest()})
    crawler = SimpleNamespace(load_json=storage.read_json, write_json=storage.write_json, utc=transport.utc)
    return corpus_checkpoint.PeriodicCheckpoint(crawler, out, {
        'enabled': True, 'archive_dir': str(out.parent / 'archives')}).build()[0]


class AtomicCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_transient_replace_reuses_fsynced_temp_and_preserves_old_destination(self):
        path = self.root / 'state.json'
        path.write_text('{"old":true}')
        original = storage.os.replace
        seen = []
        def replace(source, target):
            seen.append(Path(source))
            self.assertEqual(json.loads(Path(source).read_text()), {'new': True})
            if len(seen) < 3:
                self.assertEqual(json.loads(path.read_text()), {'old': True})
                raise PermissionError(13, 'Windows sharing violation')
            return original(source, target)
        with patch.object(storage.os, 'replace', side_effect=replace), \
                patch.object(storage.os, 'fsync', wraps=storage.os.fsync) as fsync:
            storage.write_json(path, {'new': True})
        self.assertEqual(len(seen), 3)
        self.assertEqual(len(set(seen)), 1)
        fsync.assert_called_once()
        self.assertEqual(json.loads(path.read_text()), {'new': True})
        self.assertFalse(seen[0].exists())

    def test_permanent_lock_is_bounded_unique_and_keeps_old_file_and_recovery_data(self):
        path = self.root / 'state.json'
        path.write_bytes(b'{"old":true}')
        names = []
        for value in (1, 2):
            begin = time.monotonic()
            with patch.object(storage.os, 'replace', side_effect=PermissionError(13, 'locked')) as replace:
                with self.assertRaises(storage.CheckpointError) as caught:
                    storage.write_json(path, {'new': value})
            self.assertEqual(replace.call_count, 3)
            self.assertLess(time.monotonic() - begin, 2)
            self.assertEqual(path.read_bytes(), b'{"old":true}')
            temporary = Path(caught.exception.details['checkpoint_temporary'])
            self.assertEqual(json.loads(temporary.read_text()), {'new': value})
            self.assertEqual(temporary.parent, path.parent)
            names.append(temporary)
        self.assertNotEqual(*names)

    def test_disk_full_is_not_retried_as_a_sharing_violation(self):
        with patch.object(storage.os, 'replace', side_effect=OSError(errno.ENOSPC, 'disk full')) as replace:
            with self.assertRaises(storage.CheckpointError) as caught:
                storage.write_json(self.root / 'record.json', {'id': 1})
        replace.assert_called_once()
        self.assertEqual(caught.exception.details['error_causes'][0]['errno'], errno.ENOSPC)

    def test_failed_cooldown_and_legacy_temp_survive_restart_and_merge_by_maximum(self):
        path = self.root / 'cnkang_transport_state.json'
        now = time.time()
        storage.write_json(path, {'not_before': now + 60, 'last_request': now})
        with patch.object(storage.os, 'replace', side_effect=PermissionError(13, 'locked')):
            with self.assertRaises(storage.CheckpointError):
                storage.save_state(path, {'not_before': now + 600, 'last_request': now + 1})
        self.assertEqual(json.loads(path.read_text())['not_before'], now + 60)
        path.with_suffix('.json.tmp').write_text(json.dumps({'not_before': now + 300, 'last_request': now + 2}))
        state = storage.load_state(path)
        self.assertEqual(state, {'not_before': now + 600, 'last_request': now + 2})
        storage.save_state(path, {'not_before': 0, 'last_request': 0})
        self.assertEqual(storage.load_state(path), state)
        self.assertEqual(storage.pending_paths(path), [])

    def test_invalid_state_recovery_blocks_instead_of_resetting_cooldown(self):
        path = self.root / 'cnkang_transport_state.json'
        storage.write_json(path, {'not_before': time.time() + 600})
        (self.root / '.cnkang_transport_state.json.crashed.tmp').write_bytes(b'{"not_before":')
        with self.assertRaises(storage.CheckpointError):
            transport.Transport(self.root)
        self.assertGreater(json.loads(path.read_text())['not_before'], time.time())

    def test_failed_cooldown_survives_periodic_zip_that_excludes_tmp(self):
        path = self.root / 'cnkang_transport_state.json'
        now = time.time()
        storage.write_json(path, {'not_before': now + 60})
        with patch.object(storage.os, 'replace', side_effect=PermissionError(13, 'state locked')):
            with self.assertRaises(storage.CheckpointError) as caught:
                storage.save_state(path, {'not_before': now + 600})
        self.assertTrue(caught.exception.details['checkpoint_temporary'].endswith('.recovery'))
        archive = build_backup(self.root)
        extracted = self.root / 'extracted'
        with zipfile.ZipFile(archive) as zipped:
            self.assertTrue(any(name.endswith('.recovery') for name in zipped.namelist()))
            zipped.extractall(extracted)
        restored = extracted / self.root.name
        self.assertEqual(storage.load_state(restored / path.name)['not_before'], now + 600)

    def test_journal_repairs_only_torn_tail_without_duplicate_complete_rows(self):
        path = self.root / 'journal.jsonl'
        storage.append(path, {'id': 1})
        with path.open('ab') as stream:
            stream.write(b'{"id": 2, "partial":')
        storage.append(path, {'id': 3})
        self.assertEqual([json.loads(line) for line in path.read_text().splitlines()], [{'id': 1}, {'id': 3}])

    def test_only_one_writer_and_os_releases_lock_after_process_exit(self):
        lock = storage.WriterLock(self.root)
        lock.acquire()
        other = storage.WriterLock(self.root)
        with self.assertRaises(storage.CheckpointError) as caught:
            other.acquire()
        self.assertEqual(caught.exception.details['error_code'], 'CHECKPOINT_WRITER_BUSY')
        lock.close()
        other.acquire()
        other.close()
        code = ('import sys, os; sys.path.insert(0, sys.argv[1]); import cnkang_checkpoint as s; '
                'x=s.WriterLock(sys.argv[2]); x.acquire(); os._exit(23)')
        result = subprocess.run([sys.executable, '-c', code, str(ROOT/'scripts'), str(self.root)],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 23, result.stderr)
        other.acquire()
        other.close()

    @unittest.skipUnless(os.name == 'nt', 'Windows kernel sharing violation')
    def test_actual_windows_deny_delete_lock_transient_and_permanent(self):
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        path = self.root / 'state.json'
        storage.write_json(path, {'old': True})
        def acquire():
            handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            return handle
        handle = acquire()
        try:
            begin = time.monotonic()
            with self.assertRaises(storage.CheckpointError) as caught:
                storage.write_json(path, {'new': 1})
            self.assertIn(caught.exception.details['error_causes'][0]['winerror'], (5, 32, 33))
            self.assertLess(time.monotonic() - begin, 2)
            self.assertEqual(json.loads(path.read_text()), {'old': True})
        finally:
            kernel.CloseHandle(handle)
        handle = acquire()
        original, released, attempts = storage.os.replace, False, 0
        def replace(source, target):
            nonlocal released, attempts
            attempts += 1
            try:
                return original(source, target)
            except OSError:
                if not released:
                    kernel.CloseHandle(handle)
                    released = True
                raise
        try:
            with patch.object(storage.os, 'replace', side_effect=replace):
                storage.write_json(path, {'new': 2})
        finally:
            if not released: kernel.CloseHandle(handle)
        self.assertEqual(attempts, 2)
        self.assertEqual(json.loads(path.read_text()), {'new': 2})


class Crash(BaseException):
    pass


class TransportCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sample = {'id': 1, 'url': URL, 'source_url': URL, 'canonical_url': URL}

    def net(self, name='run'):
        net = transport.Transport(self.root / name)
        self.addCleanup(net.close)
        return net

    def mock_network(self, net, reply=None):
        stack = []
        for target, name, options in [
                (net, 'wait', {}),
                (net, 'robot_policy', {'return_value': {'allowed': True, 'status': 'checked'}}),
                (net.worker, 'get', {'return_value': reply if reply is not None else response(200, page())})]:
            patcher = patch.object(target, name, **options)
            stack.append(patcher.start())
            self.addCleanup(patcher.stop)
        stack[-1].return_value.network = {'worker_pid': 999, 'elapsed_seconds': .001}
        return stack[-1]

    def test_temporary_record_lock_retries_io_without_another_get(self):
        net = self.net()
        get = self.mock_network(net)
        original, attempts = storage.os.replace, 0
        def replace(source, target):
            nonlocal attempts
            if Path(target) == net.out / 'records/1.json':
                attempts += 1
                if attempts < 3: raise PermissionError(13, 'locked')
            return original(source, target)
        with patch.object(storage.os, 'replace', side_effect=replace):
            record = net.fetch(self.sample)
        self.assertEqual(record['status'], 'extracted')
        self.assertEqual(attempts, 3)
        get.assert_called_once()
        self.assertFalse(net.stopped)
        self.assertFalse(net.pending_response_path(self.sample, 'records').exists())

    def test_permanent_record_lock_never_publishes_success_and_resume_needs_no_get(self):
        net = self.net()
        get = self.mock_network(net)
        original = storage.os.replace
        def replace(source, target):
            if Path(target) == net.out / 'records/1.json':
                raise PermissionError(13, 'locked')
            return original(source, target)
        with patch.object(storage.os, 'replace', side_effect=replace), redirect_stdout(io.StringIO()):
            with self.assertRaises(storage.CheckpointError):
                net.fetch(self.sample)
        get.assert_called_once()
        self.assertTrue(net.stopped)
        self.assertFalse((net.out / 'records/1.json').exists())
        error = json.loads((net.out / 'cnkang_checkpoint_error.json').read_text())
        self.assertEqual(error['error_code'], 'CHECKPOINT_WRITE_FAILED')
        self.assertNotEqual(error['error_kind'], 'fetch_failed')
        net.close()
        resumed = self.net()
        with patch.object(resumed.worker, 'get', side_effect=AssertionError('must reuse checkpoint')) as retry:
            record = resumed.fetch(self.sample)
        retry.assert_not_called()
        self.assertEqual(record['status'], 'extracted')
        self.assertEqual(len(list((net.out / 'records').glob('*.json'))), 1)

    def test_uncommitted_record_recovers_from_periodic_zip_without_get(self):
        net = self.net()
        self.mock_network(net)
        original = storage.os.replace
        def replace(source, target):
            if Path(target) == net.out / 'records/1.json': raise PermissionError(13, 'locked')
            return original(source, target)
        with patch.object(storage.os, 'replace', side_effect=replace), redirect_stdout(io.StringIO()):
            with self.assertRaises(storage.CheckpointError): net.fetch(self.sample)
        net.close()
        archive = build_backup(net.out)
        target = self.root / 'extracted'
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(target)
        restored = transport.Transport(target / net.out.name)
        self.addCleanup(restored.close)
        with patch.object(restored.worker, 'get', side_effect=AssertionError('duplicate GET')):
            record = restored.fetch(self.sample)
        self.assertEqual(record['status'], 'extracted')
        self.assertEqual(len(list((restored.out / 'records').glob('*.json'))), 1)

    def test_crash_after_bundle_raw_record_temp_and_record_commit_resumes_without_get(self):
        for boundary in ('bundle', 'raw', 'record_temp', 'record_commit', 'journal_tail'):
            with self.subTest(boundary=boundary):
                net = self.net(boundary)
                get = self.mock_network(net)
                original = storage.os.replace
                def replace(source, target):
                    target = Path(target)
                    if boundary == 'record_temp' and target == net.out / 'records/1.json':
                        raise Crash()
                    original(source, target)
                    if ((boundary == 'bundle' and target == net.pending_response_path(self.sample, 'records'))
                            or (boundary == 'raw' and target.parent.name == 'raw_html')
                            or (boundary == 'record_commit' and target == net.out / 'records/1.json')):
                        raise Crash()
                original_append = storage.append
                def append(path, value):
                    if boundary == 'journal_tail' and value.get('event') == 'checkpoint':
                        with Path(path).open('ab') as stream: stream.write(b'{"partial":')
                        raise Crash()
                    return original_append(path, value)
                with patch.object(storage.os, 'replace', side_effect=replace), \
                        patch.object(storage, 'append', side_effect=append):
                    with self.assertRaises(Crash): net.fetch(self.sample)
                get.assert_called_once()
                net.close()
                resumed = self.net(boundary)
                with patch.object(resumed.worker, 'get', side_effect=AssertionError('duplicate GET')) as retry:
                    record = resumed.fetch(self.sample)
                retry.assert_not_called()
                self.assertEqual(record['status'], 'extracted')
                raw = (resumed.out / record['raw_html_path']).read_bytes()
                self.assertTrue(transport.PARSER.audit(raw, record['final_url'], record)['cnkang_raw_reextraction_verified'])
                storage.append(resumed.out / 'crawl_journal.jsonl', {'event': 'resume_test'})
                for line in (resumed.out / 'crawl_journal.jsonl').read_text(encoding='utf-8').splitlines():
                    json.loads(line)

    def test_completion_state_lock_retains_response_and_last_request(self):
        net = self.net()
        get = self.mock_network(net)
        original, writes = storage.os.replace, 0
        def replace(source, target):
            nonlocal writes
            if Path(target) == net.state_path:
                writes += 1
                if writes >= 2: raise PermissionError(13, 'locked after response')
            return original(source, target)
        with patch.object(storage.os, 'replace', side_effect=replace), redirect_stdout(io.StringIO()):
            with self.assertRaises(storage.CheckpointError):
                net.fetch(self.sample)
        get.assert_called_once()
        pending = storage.load_state(net.state_path)
        self.assertGreaterEqual(pending['last_request'], json.loads(net.state_path.read_text())['last_request'])
        net.close()
        resumed = self.net()
        with patch.object(resumed.worker, 'get', side_effect=AssertionError('duplicate GET')):
            record = resumed.fetch(self.sample)
        self.assertEqual(record['status'], 'extracted')

    def test_abrupt_process_exit_after_raw_or_record_temp_releases_writer_and_recovers(self):
        code = '''
import os, sys
from pathlib import Path
sys.path[:0] = [sys.argv[1], sys.argv[2]]
import cnkang_transport as t
from test_cnkang_v6_check import page, response, URL
out, boundary = Path(sys.argv[3]), sys.argv[4]
net = t.Transport(out)
net.wait = lambda *a, **k: None
net.robot_policy = lambda url: {'allowed': True, 'status': 'checked'}
reply = response(200, page())
reply.network = {'worker_pid': 0, 'elapsed_seconds': 0}
net.worker.get = lambda *a, **k: reply
original = t.STORAGE.os.replace
def replace(source, target):
    target = Path(target)
    if boundary == 'record_temp' and target == out/'records/1.json':
        os._exit(23)
    original(source, target)
    if boundary == 'raw' and target.parent.name == 'raw_html':
        os._exit(23)
t.STORAGE.os.replace = replace
net.fetch({'id': 1, 'url': URL, 'source_url': URL, 'canonical_url': URL})
'''
        for boundary in ('raw', 'record_temp'):
            with self.subTest(boundary=boundary):
                out = self.root / ('abrupt_' + boundary)
                result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(ROOT/'scripts'),
                                         str(ROOT/'tests'), str(out), boundary],
                                        capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 23, result.stderr)
                resumed = self.net('abrupt_' + boundary)
                with patch.object(resumed.worker, 'get', side_effect=AssertionError('duplicate GET')):
                    record = resumed.fetch(self.sample)
                self.assertEqual(record['status'], 'extracted')
                raw = (resumed.out / record['raw_html_path']).read_bytes()
                self.assertTrue(transport.PARSER.audit(
                    raw, record['final_url'], record)['cnkang_raw_reextraction_verified'])

    def test_429_cooldown_is_saved_before_raw_write_can_fail(self):
        net = self.net()
        self.mock_network(net, response(429, b'busy', {'Retry-After': '600'}))
        original = storage.os.replace
        def replace(source, target):
            if Path(target).parent.name == 'raw_html':
                raise PermissionError(13, 'raw locked')
            return original(source, target)
        with patch.object(storage.os, 'replace', side_effect=replace), redirect_stdout(io.StringIO()):
            with self.assertRaises(storage.CheckpointError):
                net.fetch(self.sample)
        self.assertGreater(storage.load_state(net.state_path)['not_before'], time.time() + 590)
        net.close()
        resumed = self.net()
        with self.assertRaises(transport.Paused):
            resumed.wait()

    def test_second_writer_stops_without_changing_the_running_crawl(self):
        net = self.net()
        get = self.mock_network(net)
        net.writer.acquire()
        other = self.net()
        with redirect_stdout(io.StringIO()), self.assertRaises(storage.CheckpointError) as caught:
            other.fetch(self.sample)
        self.assertEqual(caught.exception.details['error_code'], 'CHECKPOINT_WRITER_BUSY')
        get.assert_not_called()
        self.assertFalse((net.out / 'cnkang_checkpoint_error.json').exists())

    def test_initial_state_lock_stops_before_get_and_keeps_old_cooldown(self):
        net = self.net()
        get = self.mock_network(net)
        storage.write_json(net.state_path, {'not_before': time.time() + 10, 'last_request': 12})
        original = storage.os.replace
        def replace(source, target):
            if Path(target) == net.state_path: raise PermissionError(13, 'state locked')
            return original(source, target)
        with patch.object(storage.os, 'replace', side_effect=replace), redirect_stdout(io.StringIO()):
            with self.assertRaises(storage.CheckpointError):
                net.fetch(self.sample)
        get.assert_not_called()
        self.assertEqual(json.loads(net.state_path.read_text())['last_request'], 12)
        self.assertGreater(storage.load_state(net.state_path)['not_before'], time.time())

    def test_adapter_never_counts_or_publishes_a_record_before_commit(self):
        get = Mock(return_value=response(200, page()))
        get.return_value.network = {'worker_pid': 999, 'elapsed_seconds': .001}
        original = storage.os.replace
        out = self.root / 'adapter'
        def replace(source, target):
            if Path(target) == out / 'requests_records/1.json':
                raise PermissionError(13, 'record locked')
            return original(source, target)
        published = Mock()
        with patch.object(storage.os, 'replace', side_effect=replace), \
                patch.object(transport.Transport, 'wait'), \
                patch.object(transport.Transport, 'robot_policy', return_value={'allowed': True, 'status': 'checked'}), \
                patch.object(transport.NETWORK.NetworkWorker, 'get', get), redirect_stdout(io.StringIO()):
            with self.assertRaises(storage.CheckpointError):
                transport.crawl(None, None, out, [self.sample], on_record=published)
        published.assert_not_called()
        get.assert_called_once()
        with patch.object(transport.NETWORK.NetworkWorker, 'get', side_effect=AssertionError('duplicate GET')):
            done = transport.crawl(None, None, out, [self.sample], on_record=published)
        self.assertEqual(done, 0)  # Recovered checkpoint replay is not a new network attempt.
        published.assert_called_once()
        self.assertEqual(published.call_args.args[0]['status'], 'extracted')


if __name__ == '__main__':
    unittest.main()
