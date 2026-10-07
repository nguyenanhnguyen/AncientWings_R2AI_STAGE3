"""Append-only shard logs that survive a killed Kaggle session, mirrored to a Hugging Face dataset.

A Kaggle session ends after 12 hours and /kaggle/working is not guaranteed to come back, so every
finished batch is appended and fsynced locally, and the file is pushed to the Hub every few
minutes. A restarted session pulls the file back and skips the keys already in it.
"""
import json
import os
from pathlib import Path
import time
import zlib

from ..common.console import emit


def shard_of(key, shards):
    """Stable across processes and machines, unlike hash()."""
    return zlib.crc32(str(key).encode('utf-8')) % shards


def hf_token():
    token = os.environ.get('HF_TOKEN')
    if token:
        return token
    try:
        from kaggle_secrets import UserSecretsClient

        return UserSecretsClient().get_secret('HF_TOKEN')
    except Exception:
        return None


class HubMirror:
    """Push one local file to `repo_id/path_in_repo` at most every `every` seconds."""

    def __init__(self, repo_id, path_in_repo, every=600):
        from huggingface_hub import HfApi

        self.token = hf_token()
        if not self.token:
            raise RuntimeError('No HF token: set HF_TOKEN or add the Kaggle secret HF_TOKEN.')
        self.api = HfApi(token=self.token)
        self.repo_id, self.path_in_repo, self.every = repo_id, path_in_repo, every
        self.last = time.monotonic()
        self.api.create_repo(repo_id, repo_type='dataset', private=True, exist_ok=True)

    def pull(self, local):
        """Restore the remote copy when the local file is missing (a fresh Kaggle session)."""
        from huggingface_hub import hf_hub_download
        from huggingface_hub.errors import EntryNotFoundError

        if Path(local).exists():
            return False
        try:
            path = hf_hub_download(self.repo_id, self.path_in_repo, repo_type='dataset',
                                   token=self.token)
        except EntryNotFoundError:
            return False
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        Path(local).write_bytes(Path(path).read_bytes())
        emit(f'Khôi phục {self.path_in_repo} từ Hub.')
        return True

    def push(self, local, force=False):
        if not force and time.monotonic() - self.last < self.every:
            return
        for attempt in range(3):
            try:
                self.api.upload_file(path_or_fileobj=str(local), path_in_repo=self.path_in_repo,
                                     repo_id=self.repo_id, repo_type='dataset',
                                     commit_message=f'sync {self.path_in_repo}')
                self.last = time.monotonic()
                return
            except Exception as error:  # network blips must not kill a 12-hour run
                emit(f'Hub upload lỗi (lần {attempt + 1}): {error}')
                time.sleep(10 * (attempt + 1))


class ShardLog:
    """JSONL keyed by `key_field`; a torn last line from a killed process is dropped on open."""

    def __init__(self, path, key_field, mirror=None):
        self.path, self.key_field, self.mirror = Path(path), key_field, mirror
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if mirror:
            mirror.pull(self.path)
        self.done = set()
        good = []
        if self.path.exists():
            with self.path.open(encoding='utf-8') as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self.done.add(row[key_field])
                    good.append(line if line.endswith('\n') else line + '\n')
            self.path.write_text(''.join(good), encoding='utf-8')

    def append(self, rows):
        with self.path.open('a', encoding='utf-8') as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                self.done.add(row[self.key_field])
            stream.flush()
            os.fsync(stream.fileno())
        if self.mirror:
            self.mirror.push(self.path)

    def close(self):
        if self.mirror:
            self.mirror.push(self.path, force=True)


def open_log(out, stage, shard, shards, key_field, hub_repo=None, sync_minutes=10):
    name = f'{stage}/shard_{shard:02d}_of_{shards:02d}.jsonl'
    mirror = HubMirror(hub_repo, f'teach/{name}', every=sync_minutes * 60) if hub_repo else None
    return ShardLog(Path(out) / name, key_field, mirror)


def read_stage(out, stage):
    """Every row of every shard of one stage, last write wins per key."""
    rows = []
    for path in sorted((Path(out) / stage).glob('shard_*.jsonl')):
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def push_inputs(repo_id, root, files):
    """Laptop -> Hub: the code and the input files a Kaggle session needs, under code/ and inputs/."""
    from huggingface_hub import HfApi

    token = hf_token()
    if not token:
        raise RuntimeError('Set HF_TOKEN (a write token) before pushing.')
    api = HfApi(token=token)
    api.create_repo(repo_id, repo_type='dataset', private=True, exist_ok=True)
    root = Path(root)
    for folder in ('src', 'scripts'):
        api.upload_folder(folder_path=str(root / folder), path_in_repo=f'code/{folder}',
                          repo_id=repo_id, repo_type='dataset',
                          allow_patterns=['*.py'], delete_patterns=['*.py'],
                          commit_message=f'code/{folder}')
    for path in files:
        api.upload_file(path_or_fileobj=str(path), path_in_repo=f'inputs/{Path(path).name}',
                        repo_id=repo_id, repo_type='dataset',
                        commit_message=f'inputs/{Path(path).name}')
        emit(f'đã đẩy inputs/{Path(path).name}')


class Deadline:
    """Stop cleanly before Kaggle kills the session, so the last batch is saved and pushed."""

    def __init__(self, hours):
        self.end = time.monotonic() + hours * 3600 if hours else None

    def passed(self):
        return self.end is not None and time.monotonic() > self.end
