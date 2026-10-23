"""Bound DNS lookup time without changing addresses, TLS, or crawler URL validation."""
import socket
import math
import threading
import time

VERSION = 'ask39-bounded-dns-v1'


class BoundedResolver:
    def __init__(self, lookup=None, timeout=5.0, ttl=60.0, max_inflight=2):
        if (isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0
                or isinstance(ttl, bool) or not math.isfinite(ttl) or ttl < 0
                or type(max_inflight) is not int or max_inflight < 1):
            raise ValueError('Invalid DNS timeout/cache/worker limit')
        self.lookup = lookup or socket.getaddrinfo
        self.timeout, self.ttl = timeout, ttl
        self._slots = threading.BoundedSemaphore(max_inflight)
        self._lock = threading.Lock()
        self._cache = {}
        self._pending = {}

    def __call__(self, host, port, family=0, type=0, proto=0, flags=0):
        key = (host, port, family, type, proto, flags)
        deadline = time.monotonic()+self.timeout
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                return list(cached[1])
            pending = self._pending.get(key)
            if pending is None:
                if not self._slots.acquire(blocking=False):
                    raise socket.gaierror(socket.EAI_AGAIN, 'DNS resolver worker limit reached')
                pending = {'event': threading.Event()}
                self._pending[key] = pending
                def work():
                    try:
                        addresses = self.lookup(host, port, family, type, proto, flags)
                        pending['addresses'] = tuple(addresses)
                        with self._lock:
                            self._cache[key] = (time.monotonic()+self.ttl, tuple(addresses))
                    except Exception as exc:
                        pending['error'] = exc
                    finally:
                        with self._lock:
                            self._pending.pop(key, None)
                        self._slots.release()
                        pending['event'].set()
                # A stuck system resolver must not keep the calling process alive.
                threading.Thread(target=work, name='ask39-dns', daemon=True).start()
        if not pending['event'].wait(max(0, deadline-time.monotonic())):
            raise socket.gaierror(socket.EAI_AGAIN, 'DNS lookup exceeded %.3fs: %s' % (self.timeout, host))
        if 'error' in pending:
            raise pending['error']
        return list(pending['addresses'])

    def close(self):
        if socket.getaddrinfo is self:
            socket.getaddrinfo = self.lookup


def install(timeout=5.0, ttl=60.0, max_inflight=2):
    if isinstance(socket.getaddrinfo, BoundedResolver):
        return socket.getaddrinfo
    resolver = BoundedResolver(timeout=timeout, ttl=ttl, max_inflight=max_inflight)
    socket.getaddrinfo = resolver
    return resolver
