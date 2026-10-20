"""R1 regression tests: actual killable processes, budgets and error provenance."""
import ast
import base64
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import cnkang_transport as transport

network = transport.NETWORK
WORKER = ROOT / 'scripts/cnkang_request_worker.py'
FIXTURE = ROOT / 'tests/fixtures/cnkang_r1/network_scenarios.py'


class DeadlineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # The launched process executes production serve(); only its network is simulated.
        bootstrap = self.root / 'worker.py'
        bootstrap.write_text(
            'import runpy, sys\nsys.argv = ' + repr([str(FIXTURE), str(WORKER)]) +
            '\nrunpy.run_path(sys.argv[0], run_name="__main__")\n', encoding='utf-8')
        self.override = patch.object(network, 'WORKER_PATH', bootstrap)
        self.override.start()
        self.addCleanup(self.override.stop)
        self.worker = network.NetworkWorker()
        self.addCleanup(self.worker.close)

    def request(self, scenario, seconds=1.5, scope='request'):
        return self.worker.get('https://www.cnkang.com/' + scenario,
                               transport.DEFAULTS, network.deadline(seconds), scope=scope)

    def test_hung_dns_headers_and_drip_body_killed_no_orphan_or_late_result(self):
        for scenario, stage in [('dns-hang', 'dns'), ('headers-hang', 'read_headers'),
                                ('slow-body', 'read_body')]:
            with self.subTest(scenario=scenario):
                self.worker.start()
                process, reader = self.worker.process, self.worker.reader
                begin = time.monotonic()
                with self.assertRaises(network.NetworkFailure) as caught:
                    self.request(scenario)
                self.assertEqual(caught.exception.details['error_kind'], 'request_deadline')
                self.assertEqual(caught.exception.details['error_stage'], stage)
                self.assertLess(time.monotonic() - begin, 3.5)
                self.assertIsNotNone(process.poll())
                self.assertFalse(reader.is_alive())
                self.assertIsNone(self.worker.process)
                # A fresh worker must not receive the killed request's late reply.
                self.assertEqual(self.request('ok', 5).content, b'ok')

    def test_dns_reset_and_wrapped_body_timeout_keep_original_causes(self):
        for scenario, kind, cause in [('dns-error', 'dns_error', 'gaierror'),
                                     ('reset', 'connection_reset', 'ConnectionResetError'),
                                     ('body-timeout', 'read_timeout', 'ReadTimeoutError')]:
            with self.subTest(scenario=scenario), self.assertRaises(network.NetworkFailure) as caught:
                self.request(scenario, 5)
            details = caught.exception.details
            self.assertEqual(details['error_kind'], kind)
            self.assertIn(cause, {item['type'] for item in details['error_causes']})

    def test_success_reuses_one_session_and_size_limit_is_enforced(self):
        one, two = self.request('ok', 5), self.request('ok', 5)
        self.assertEqual(one.network['worker_pid'], two.network['worker_pid'])
        self.assertEqual(two.headers['X-Session-Count'], '2')
        with self.assertRaises(network.NetworkFailure) as caught:
            self.worker.get('https://www.cnkang.com/ok', {**transport.DEFAULTS, 'max_bytes': 1},
                            network.deadline(5))
        self.assertEqual(caught.exception.details['error_kind'], 'response_too_large')

    def test_stale_result_rejected_after_clock_jump(self):
        self.worker.start()
        limit = network.deadline(10)
        real_remaining = network.remaining
        count = 0
        def remaining(value):
            nonlocal count
            count += 1
            return real_remaining(value) if count <= 2 else -1
        with patch.object(network, 'remaining', side_effect=remaining):
            with self.assertRaises(network.NetworkFailure) as caught:
                self.worker.get('https://www.cnkang.com/ok', transport.DEFAULTS, limit)
        self.assertTrue(caught.exception.details['deadline_exceeded'])
        self.assertIsNone(self.worker.process)

    def test_worker_launch_failure_is_network_error_and_expired_budget_starts_nothing(self):
        with patch.object(network.subprocess, 'Popen', side_effect=OSError(5, 'worker launch denied')):
            with self.assertRaises(network.NetworkFailure) as caught:
                self.request('ok', 5)
        self.assertEqual(caught.exception.details['error_kind'], 'network_worker_error')
        self.assertEqual(caught.exception.details['error_stage'], 'worker_start')
        self.assertEqual(caught.exception.details['error_causes'][0]['errno'], 5)
        with patch.object(network.subprocess, 'Popen') as start:
            with self.assertRaises(network.NetworkFailure):
                self.worker.get('https://www.cnkang.com/ok', transport.DEFAULTS, network.deadline(-1))
        start.assert_not_called()

    def test_url_budget_clamps_robot_request_and_checkpoints_real_stage(self):
        net = transport.Transport(self.root / 'run', {'url_deadline': 1.5, 'request_deadline': 45})
        self.addCleanup(net.close)
        sample = {'id': 1, 'url': 'http://www.cnkang.com/myjk/1.html'}
        # Focus this case on DNS after the worker is ready. Under concurrent disk
        # load a cold interpreter may itself consume the 1.5s budget and correctly
        # report worker_start instead; startup deadlines have separate coverage.
        net.worker.get('https://www.cnkang.com/ok', net.config, network.deadline(10))
        # robots request stalls in DNS, not in a page fetch.
        original_get = net.worker.get
        def stalled(url, config, limit, **kwargs):
            return original_get('https://www.cnkang.com/dns-hang', config, limit, **kwargs)
        with patch.object(net.worker, 'get', side_effect=stalled):
            record = net.fetch(sample)
        self.assertEqual(record['error_kind'], 'url_deadline')
        self.assertEqual(record['error_stage'], 'dns')
        self.assertEqual(record['error_context'], 'robots')
        self.assertEqual(record['requests'], [])
        self.assertLess(record['elapsed_seconds'], 3.5)
        self.assertTrue(net.stopped)
        self.assertEqual(json.loads((net.out / 'records/1.json').read_text())['error_stage'], 'dns')

    def test_dns_retry_stays_https_and_robots_failure_does_not_mask_dns(self):
        net = transport.Transport(self.root / 'run')
        self.addCleanup(net.close)
        sample = {'id': 2, 'url': 'http://www.cnkang.com/myjk/2.html'}
        error = transport.NetworkFailure({'error_kind': 'dns_error', 'error_stage': 'dns',
                                          'error': 'getaddrinfo failed', 'error_causes': []})
        robot = {'allowed': True, 'status': 'checked'}
        with patch.object(net, 'robot_policy', return_value=robot), patch.object(net, 'wait'), \
                patch.object(net, 'get', side_effect=error) as get:
            record = net.fetch(sample)
        self.assertEqual(record['error_kind'], 'dns_error')
        self.assertEqual(get.call_count, 2)
        self.assertTrue(all(call.args[0].startswith('https:') for call in get.call_args_list))
        with patch.object(net, 'get', side_effect=error):
            record = net.fetch(dict(sample, id=3))
        self.assertEqual(record['error_kind'], 'dns_error')
        self.assertEqual(record['error_context'], 'robots')
        self.assertIn('getaddrinfo', record['error'])

    def test_worker_launch_failure_in_robots_stops_with_correct_cause(self):
        net = transport.Transport(self.root / 'launch-failure')
        self.addCleanup(net.close)
        with patch.object(network.subprocess, 'Popen', side_effect=OSError(5, 'worker launch denied')):
            record = net.fetch({'id': 5, 'url': 'https://www.cnkang.com/myjk/5.html'})
        self.assertEqual(record['error_kind'], 'network_worker_error')
        self.assertEqual(record['error_context'], 'robots')
        self.assertEqual(record['error_stage'], 'worker_start')
        self.assertEqual(record['stop_reason'], 'network_worker_error')
        self.assertTrue(net.stopped)

    def test_wait_and_redirects_cannot_extend_url_budget(self):
        net = transport.Transport(self.root / 'run', {'url_deadline': .3})
        self.addCleanup(net.close)
        sample = {'id': 3, 'url': 'https://www.cnkang.com/myjk/3.html'}
        net.state['last_request'] = time.time()
        record = net.fetch(sample)
        self.assertEqual(record['error_kind'], 'url_deadline')
        self.assertEqual(record['error_stage'], 'throttle')
        self.assertEqual(record['network_requests'], [])

        net.state.clear()
        reply = transport.requests.Response()
        reply.status_code = 302
        reply._content = b''
        reply.headers['Location'] = sample['url']
        def redirect(url):
            time.sleep(.12)
            return reply
        with patch.object(net, 'robot_policy', return_value={'allowed': True, 'status': 'checked'}), \
                patch.object(net, 'wait'), patch.object(net, 'get', side_effect=redirect):
            record = net.fetch(dict(sample, id=4))
        self.assertEqual(record['error_kind'], 'url_deadline')
        self.assertLess(record['elapsed_seconds'], .7)


class SnapshotTests(unittest.TestCase):
    def test_main_and_check_include_identical_network_and_checkpoint_modules(self):
        packages = []
        for name in ('crawl_corpus_kaggle_hf_upload.ipynb', 'check_cnkang.com.ipynb'):
            values = {}
            nb = json.loads((ROOT / 'notebooks' / name).read_text(encoding='utf-8'))
            for cell in nb['cells']:
                if cell['cell_type'] != 'code': continue
                for node in ast.parse(''.join(cell['source'])).body:
                    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                        if node.targets[0].id in ('PAYLOADS', 'EMBEDDED_FILES'):
                            values.update(ast.literal_eval(node.value))
            packages.append(values)
        for name in ('cnkang_network_snapshot.py', 'cnkang_request_worker_snapshot.py',
                     'cnkang_checkpoint_snapshot.py', 'cnkang_article_snapshot.py'):
            self.assertEqual(packages[0][name], packages[1][name])
            body = zlib.decompress(base64.b85decode(packages[0][name]))
            self.assertEqual(body, (ROOT / 'scripts' / name.replace('_snapshot', '')).read_bytes())


if __name__ == '__main__':
    unittest.main()
