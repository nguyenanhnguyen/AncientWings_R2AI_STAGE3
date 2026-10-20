"""No external sockets: run the real worker protocol with controllable network stalls."""
import importlib.util
import json
from pathlib import Path
import socket
import sys
import time

import requests
import urllib3.connection
from urllib3.exceptions import ReadTimeoutError

source = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('real_worker', source)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def resolve(host, *args, **kwargs):
    if host == 'dns-hang':
        time.sleep(60)
    if host == 'dns-error':
        raise socket.gaierror(11001, 'getaddrinfo failed')
    return []


class Reply:
    status_code = 200
    headers = {'Content-Type': 'text/plain', 'Set-Cookie': 'test=1'}
    url = 'https://www.cnkang.com/test.html'

    def __init__(self, scenario):
        self.scenario = scenario

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        if self.scenario == 'slow-body':
            for _ in range(1000):
                time.sleep(.1)
                yield b'x'
        elif self.scenario == 'body-timeout':
            raise requests.ConnectionError(ReadTimeoutError(None, self.url, 'read timed out'))
        else:
            yield b'ok'


class Session:
    def __init__(self):
        self.headers = {}
        self.count = 0

    def get(self, url, **kwargs):
        scenario = url.rstrip('/').split('/')[-1]
        socket.getaddrinfo(scenario, 443)
        if scenario == 'reset':
            raise requests.ConnectionError(ConnectionResetError(10054, 'reset'))
        if scenario == 'headers-hang':
            urllib3.connection.HTTPConnection.getresponse(None)
        self.count += 1
        reply = Reply(scenario)
        reply.headers = {**reply.headers, 'X-Session-Count': str(self.count)}
        return reply

    def close(self):
        pass


socket.getaddrinfo = resolve
urllib3.connection.HTTPConnection.getresponse = lambda *a, **k: time.sleep(60)
requests.Session = Session


def emit(message):
    print(json.dumps(message), flush=True)


worker.serve(sys.stdin, emit)
