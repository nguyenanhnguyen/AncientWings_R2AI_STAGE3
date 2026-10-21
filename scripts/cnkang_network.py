"""Supervise a killable network process; DNS and streamed bodies share a hard limit."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

import requests


WORKER_PATH = Path(__file__).with_name('cnkang_request_worker_snapshot.py')
if not WORKER_PATH.exists():
    WORKER_PATH = Path(__file__).with_name('cnkang_request_worker.py')


class NetworkFailure(requests.RequestException):
    def __init__(self, details):
        self.details = details
        super().__init__(details['error'])


def deadline(seconds):
    return (time.monotonic() + seconds, time.time() + seconds)


def remaining(limit):
    return min(limit[0] - time.monotonic(), limit[1] - time.time())


class NetworkWorker:
    def __init__(self):
        self.process = self.reader = self.messages = None

    def start(self):
        if self.process is not None and self.process.poll() is None:
            return
        self.close()
        self.process = subprocess.Popen(
            [sys.executable, '-u', str(WORKER_PATH)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.messages = queue.Queue()
        stream, messages = self.process.stdout, self.messages

        def read():
            try:
                for line in stream:
                    messages.put(json.loads(line))
            except Exception as exc:
                messages.put({'event': 'pipe_error', 'error': repr(exc)})
            finally:
                messages.put({'event': 'eof'})
        self.reader = threading.Thread(target=read, name='cnkang-worker-pipe', daemon=True)
        self.reader.start()

    def close(self):
        process, reader = self.process, self.reader
        self.process = self.reader = self.messages = None
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass  # A crashed worker may already have closed its end of the pipe.
        if reader is not None:
            reader.join(timeout=1)
            if reader.is_alive():
                raise RuntimeError('cnkang network pipe reader did not stop')

    def get(self, url, config, limit, *, scope='request'):
        stage, begin = 'worker_start', time.monotonic()
        pid = None

        def expired():
            return NetworkFailure({'error_kind': scope + '_deadline', 'error_stage': stage,
                                   'error': f'{scope} deadline exceeded during {stage}',
                                   'request_url': url, 'worker_pid': pid,
                                   'deadline_exceeded': True, 'error_causes': []})

        try:
            if remaining(limit) <= 0:
                raise expired()
            self.start()
            pid = self.process.pid
            if remaining(limit) <= 0:
                raise expired()
            command = {'url': url, 'config': {key: config[key] for key in
                       ('timeout', 'max_bytes', 'trust_env', 'user_agent')}}
            self.process.stdin.write((json.dumps(command) + '\n').encode('utf-8'))
            self.process.stdin.flush()
            while remaining(limit) > 0:
                try:
                    message = self.messages.get(timeout=max(0., min(remaining(limit), .1)))
                except queue.Empty:
                    continue
                # Reject results arriving after expiry, including after OS suspend/resume.
                if remaining(limit) <= 0:
                    break
                if message['event'] == 'stage':
                    stage = message['stage']
                elif message['event'] == 'error':
                    raise NetworkFailure({**message, 'request_url': url, 'worker_pid': pid})
                elif message['event'] == 'result':
                    response = requests.Response()
                    response.status_code, response.url = message['status'], message['url']
                    response.headers.update(message['headers'])
                    response._content = base64.b64decode(message['body'], validate=True)
                    if remaining(limit) <= 0:
                        break
                    response.network = {'worker_pid': pid, 'elapsed_seconds':
                                        round(time.monotonic() - begin, 3)}
                    return response
                else:
                    raise NetworkFailure({'error_kind': 'network_worker_error', 'error_stage': stage,
                                          'error': message.get('error', 'Network worker exited'),
                                          'request_url': url, 'worker_pid': pid, 'error_causes': []})
            raise expired()
        except NetworkFailure:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise NetworkFailure({'error_kind': 'network_worker_error', 'error_stage': stage,
                                  'error': f'{type(exc).__name__}: {exc}'[:700],
                                  'request_url': url, 'worker_pid': pid,
                                  'error_causes': [{'type': type(exc).__name__, 'message': str(exc)[:700],
                                                    'errno': exc.errno,
                                                    'winerror': getattr(exc, 'winerror', None)}]}) from exc
        except BaseException:
            self.close()
            raise
