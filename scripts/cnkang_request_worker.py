"""Isolated, persistent Requests session. Only the supervisor writes crawl files."""
from __future__ import annotations

import base64
import json
import socket
import sys

import requests
import urllib3.connection


def causes(exc):
    pending, seen, result = [exc], set(), []
    while pending:
        item = pending.pop(0)
        if not isinstance(item, BaseException) or id(item) in seen:
            continue
        seen.add(id(item))
        result.append({'type': type(item).__name__, 'message': str(item)[:700],
                       'errno': getattr(item, 'errno', None),
                       'winerror': getattr(item, 'winerror', None)})
        pending.extend([getattr(item, name, None)
                        for name in ('__cause__', '__context__', 'reason', '_reason')])
        pending.extend(arg for arg in item.args if isinstance(arg, BaseException))
    return result


def classify(exc, stage):
    chain = causes(exc)
    names = {item['type'] for item in chain}
    if names & {'gaierror', 'NameResolutionError'}:
        kind = 'dns_error'
    elif names & {'ConnectTimeout', 'ConnectTimeoutError'}:
        kind = 'connect_timeout'
    elif names & {'ReadTimeout', 'ReadTimeoutError'}:
        kind = 'read_timeout'
    elif names & {'ConnectionResetError'} or any(
            item['errno'] in (54, 104, 10054) or item['winerror'] == 10054 for item in chain):
        kind = 'connection_reset'
    elif isinstance(exc, requests.ConnectionError):
        kind = 'connection_error'
    elif isinstance(exc, ValueError):
        kind = 'response_too_large'
    else:
        kind = 'request_error'
    return dict(error_kind=kind, error_stage=stage, error=f'{type(exc).__name__}: {exc}'[:700],
                error_causes=chain)


def serve(input_stream, emit):
    session = requests.Session()
    stage = 'worker_start'

    def phase(name):
        nonlocal stage
        stage = name
        emit({'event': 'stage', 'stage': name})

    original_dns = socket.getaddrinfo
    original_response = urllib3.connection.HTTPConnection.getresponse

    def resolve(*args, **kwargs):
        phase('dns')
        answer = original_dns(*args, **kwargs)
        phase('connect')
        return answer

    def getresponse(connection, *args, **kwargs):
        phase('read_headers')
        return original_response(connection, *args, **kwargs)

    socket.getaddrinfo = resolve
    urllib3.connection.HTTPConnection.getresponse = getresponse
    try:
        for line in input_stream:
            command = json.loads(line)
            config = command['config']
            session.trust_env = config['trust_env']
            session.headers.update({'User-Agent': config['user_agent'],
                                    'Accept': 'text/html,application/xhtml+xml'})
            try:
                phase('connect')
                with session.get(command['url'], timeout=tuple(config['timeout']),
                                 allow_redirects=False, stream=True) as response:
                    phase('read_body')
                    data = bytearray()
                    for chunk in response.iter_content(65536):
                        data.extend(chunk)
                        if len(data) > config['max_bytes']:
                            raise ValueError('Response exceeds configured size limit')
                    emit({'event': 'result', 'status': response.status_code,
                          'headers': dict(response.headers), 'url': response.url,
                          'body': base64.b64encode(data).decode('ascii')})
            except Exception as exc:
                emit({'event': 'error', **classify(exc, stage)})
    finally:
        session.close()
        socket.getaddrinfo = original_dns
        urllib3.connection.HTTPConnection.getresponse = original_response


if __name__ == '__main__':
    def emit(value):
        sys.stdout.write(json.dumps(value, ensure_ascii=True) + '\n')
        sys.stdout.flush()
    serve(sys.stdin, emit)
