"""Single-writer atomic checkpoints, bounded Windows sharing retries and recovery."""
from __future__ import annotations

import errno
import json
import math
import os
from pathlib import Path
import tempfile
import time

ATTEMPTS = 3
RETRY_BUDGET = 2.
BACKOFF = (.1, .2)


class CheckpointError(OSError):
    def __init__(self, path, operation, cause, *, temporary=None, attempts=0):
        self.details = {
            'error_kind': 'checkpoint_write_failed', 'error_stage': 'checkpoint',
            'error_code': 'CHECKPOINT_WRITE_FAILED', 'checkpoint_path': str(path),
            'checkpoint_operation': operation, 'checkpoint_attempts': attempts,
            'checkpoint_temporary': str(temporary) if temporary else None,
            'error_causes': [{'type': type(cause).__name__, 'message': str(cause)[:700],
                              'errno': getattr(cause, 'errno', None),
                              'winerror': getattr(cause, 'winerror', None)}]}
        self.details['error'] = f'CHECKPOINT_WRITE_FAILED: {operation}: {path}: {cause}'[:1200]
        super().__init__(self.details['error'])


def sharing_error(exc):
    return (isinstance(exc, PermissionError) or getattr(exc, 'winerror', None) in (5, 32, 33)
            or getattr(exc, 'errno', None) in (errno.EACCES, errno.EPERM))


def retry(operation, path, label, *, temporary=None):
    deadline = time.monotonic() + RETRY_BUDGET
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return operation()
        except OSError as exc:
            if (not sharing_error(exc) or attempt == ATTEMPTS
                    or time.monotonic() + BACKOFF[attempt - 1] >= deadline):
                raise CheckpointError(path, label, exc, temporary=temporary, attempts=attempt) from exc
            time.sleep(BACKOFF[attempt - 1])


def pending_paths(path):
    path = Path(path)
    # Legacy fixed .tmp is included to preserve state from the original WinError 5.
    return sorted([*path.parent.glob('.' + path.name + '.*.tmp'),
                   *path.parent.glob('.' + path.name + '.*.recovery'),
                   *([path.with_suffix(path.suffix + '.tmp')]
                     if path.with_suffix(path.suffix + '.tmp').exists() else [])],
                  key=lambda p: p.stat().st_mtime_ns, reverse=True)


def discard(path):
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass  # A committed file is authoritative; a stale recovery copy is harmless.


def write_bytes(path, body):
    path, temporary = Path(path), None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise CheckpointError(path, 'write_and_fsync', exc, temporary=temporary) from exc
    # Never remove/truncate the old destination, even after permanent sharing failure.
    try:
        retry(lambda: os.replace(temporary, path), path, 'replace', temporary=temporary)
    except CheckpointError as exc:
        # Complete, fsynced data must survive backup tools that exclude .tmp.
        # .recovery also avoids being mistaken for a committed per-ID *.json.
        recovery = temporary.with_suffix('.recovery')
        try:
            os.rename(temporary, recovery)
            exc.details['checkpoint_temporary'] = str(recovery)
        except OSError:
            pass  # Retain the original temp if even this private rename is denied.
        raise


def write_json(path, value):
    try:
        body = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError) as exc:
        raise CheckpointError(path, 'serialize_json', exc) from exc
    write_bytes(path, body)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise CheckpointError(path, 'read_or_recover', exc) from exc


def load_state(path):
    """Conservative merge; a failed/newer cooldown must never be lost on restart."""
    path = Path(path)
    candidates = ([path] if path.exists() else []) + pending_paths(path)
    state = {}
    for candidate in candidates:
        value = read_json(candidate)
        if not isinstance(value, dict) or any(
                not isinstance(value.get(key, 0), (int, float))
                or not math.isfinite(value.get(key, 0)) or value.get(key, 0) < 0
                for key in ('not_before', 'last_request')):
            raise CheckpointError(candidate, 'recover_state', ValueError('Invalid transport state'))
        for key, item in value.items():
            if key not in ('not_before', 'last_request'):
                state.setdefault(key, item)
        for key in ('not_before', 'last_request'):
            if key in value:
                state[key] = max(state.get(key, 0), value[key])
    return state


def save_state(path, value):
    previous = load_state(path)
    merged = {**previous, **value}
    for key in ('not_before', 'last_request'):
        if key in previous or key in value:
            merged[key] = max(previous.get(key, 0), value.get(key, 0))
    old_pending = pending_paths(path)
    write_json(path, merged)
    for pending in old_pending:
        discard(pending)
    return merged


def append(path, value):
    """Journal is diagnostic; atomic per-ID records are the resume authority."""
    path = Path(path)
    body = (json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = retry(lambda: path.open('a+b'), path, 'open_journal')
        with stream:
            stream.seek(0, os.SEEK_END)
            end = stream.tell()
            if end:
                stream.seek(end - 1)
                if stream.read(1) != b'\n':
                    # Repair only a torn last line; never replay a possibly partial append.
                    position, found = end, -1
                    while position and found < 0:
                        start = max(0, position - 65536)
                        stream.seek(start)
                        block = stream.read(position - start)
                        index = block.rfind(b'\n')
                        if index >= 0:
                            found = start + index
                        position = start
                    stream.truncate(found + 1)
            stream.seek(0, os.SEEK_END)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    except CheckpointError:
        raise
    except OSError as exc:
        raise CheckpointError(path, 'append_and_fsync', exc) from exc


class WriterLock:
    """OS releases the lock after crash; do not unlink the shared lock inode."""
    def __init__(self, out):
        self.path = Path(out) / '.cnkang_writer.lock'
        self.stream = None

    def acquire(self):
        if self.stream is not None:
            return
        stream, locking = None, False
        try:
            stream = self.path.open('a+b')
            stream.seek(0, os.SEEK_END)
            if not stream.tell():
                stream.write(b'\0')
                stream.flush()
            stream.seek(0)
            locking = True
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.stream = stream
        except OSError as exc:
            if stream is not None: stream.close()
            error = CheckpointError(self.path, 'acquire_writer' if locking else 'open_writer', exc)
            if locking:
                error.details.update(error_code='CHECKPOINT_WRITER_BUSY', error_kind='checkpoint_writer_busy')
            raise error from exc

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None
