"""Periodic full checkpoints; publish ZIP and its checksum in one Hugging Face commit."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import zipfile

DEFAULTS = {'enabled': False, 'upload': False, 'repo_id': 'AncientWings/AncientWings_R2AI_STAGE3_ds',
    'every_urls': 10000, 'every_seconds': 900., 'upload_attempts': 3, 'failure_retry_seconds': 120.,
    'token_env': 'HF_TOKEN', 'archive_dir': None}


def validate_config(config):
    config = {**DEFAULTS, **config}
    for key in ('enabled', 'upload'):
        if type(config[key]) is not bool: raise ValueError(f'Checkpoint {key} must be bool.')
    for key in ('every_urls', 'upload_attempts'):
        if type(config[key]) is not int or config[key] < 1: raise ValueError(f'Invalid checkpoint {key}.')
    for key in ('every_seconds', 'failure_retry_seconds'):
        if not isinstance(config[key], (int,float)) or not math.isfinite(config[key]) or config[key] <= 0:
            raise ValueError(f'Invalid checkpoint {key}.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', config['repo_id']):
        raise ValueError('Checkpoint repo_id must be owner/dataset.')
    if not re.fullmatch(r'[A-Z_][A-Z0-9_]*', config['token_env']): raise ValueError('Invalid token environment name.')
    if config['archive_dir'] is not None: config['archive_dir'] = str(config['archive_dir'])
    return config


def sha_file(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_error(exc, token):
    text = str(exc).replace(token, '[redacted]') if token else str(exc)
    text = re.sub(r'\bhf_[A-Za-z0-9]{8,}\b', '[redacted]', text)
    text = re.sub(r'(?i)Bearer\s+\S+', 'Bearer [redacted]', text)
    text = re.sub(r'(https?://[^\s?]+)\?[^\s]+', r'\1?[redacted]', text)
    return text[:1200]


class PeriodicCheckpoint:
    def __init__(self, crawler, out, config):
        self.crawler, self.out, self.config = crawler, Path(out), validate_config(config)
        self.state_path = self.out / 'checkpoint_upload_state.json'
        self.state = crawler.load_json(self.state_path) if self.state_path.exists() else {}
        self.observed = (len(list((self.out/'records').glob('*.json'))) if self.config['enabled'] else 0)
        self.last_saved = self.observed
        self.last_time = time.monotonic()
        self.last_attempt = float('-inf')

    def counts(self):
        manifest = self.crawler.load_json(self.out/'manifest.json')
        selected = manifest['selected']
        sample_path=self.out/'sample.jsonl'
        if sha_file(sample_path)!=manifest['sample_sha256']: raise ValueError('Checkpoint sample hash mismatch.')
        with sample_path.open(encoding='utf-8') as stream:
            expected={r['id']:r['url'] for r in (json.loads(line) for line in stream if line.strip())}
        if len(expected)!=selected: raise ValueError('Checkpoint sample count mismatch.')
        seen, accepted=set(),0
        for path in (self.out/'records').glob('*.json'):
            r=self.crawler.load_json(path)
            if r['id'] in seen or expected.get(r['id'])!=r.get('url'):
                raise ValueError('Checkpoint contains duplicate/unexpected IDs.')
            if 'text' in r and hashlib.sha256(r['text'].encode()).hexdigest()!=r.get('text_sha256'):
                raise ValueError('Checkpoint text hash mismatch.')
            seen.add(r['id'])
            accepted+=r.get('quality_status')=='accepted'
        return {'selected':selected,'completed':len(seen),'pending':selected-len(seen),'accepted':accepted}

    def build(self):
        archive_dir = Path(self.config['archive_dir']) if self.config['archive_dir'] else self.out.parent.parent
        archive_dir.mkdir(parents=True, exist_ok=True)
        if archive_dir.resolve().is_relative_to(self.out.resolve()):
            raise ValueError('Checkpoint ZIP must be outside the run directory.')
        archive = archive_dir / (self.out.name+'_checkpoint.zip')
        temporary = archive.with_suffix('.zip.tmp')
        counts = self.counts()
        progress = {'kind': 'crawl_checkpoint', 'complete': False, 'crawl_complete': counts['pending']==0,
            **counts, 'created_at': self.crawler.utc(), 'run_name': self.out.name,
            'source_manifest_sha256': sha_file(self.out/'manifest.json'), 'sample_sha256': sha_file(self.out/'sample.jsonl')}
        self.crawler.write_json(self.out/'checkpoint_progress.json',progress)
        try:
            with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,allowZip64=True) as z:
                for path in sorted(self.out.rglob('*')):
                    if path.is_symlink(): raise ValueError('Checkpoint run contains a symlink.')
                    if not path.is_file() or path.suffix in ('.tmp','.lock') or '__pycache__' in path.parts:
                        continue
                    z.write(path, self.out.name+'/'+path.relative_to(self.out).as_posix())
            with zipfile.ZipFile(temporary) as z:
                if z.testzip() is not None: raise ValueError('Checkpoint ZIP checksum failure.')
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
        proof = dict(progress, archive_bytes=archive.stat().st_size, archive_sha256=sha_file(archive),
                     archive_path=f'checkpoints/{self.out.name}/latest.zip')
        self.crawler.write_json(archive.with_suffix('.json'),proof)
        return archive, proof

    def upload(self, archive, proof):
        token = os.environ.get(self.config['token_env'],'')
        if not token: raise RuntimeError('No HF_TOKEN for durable checkpoint; local ZIP is available.')
        from huggingface_hub import HfApi, CommitOperationAdd
        api = HfApi(token=token)
        for attempt in range(1,self.config['upload_attempts']+1):
            try:
                # Operations are rebuilt each attempt because the Hub mutates them while uploading.
                commit = api.create_commit(repo_id=self.config['repo_id'],repo_type='dataset',
                    operations=[CommitOperationAdd(path_in_repo=proof['archive_path'],path_or_fileobj=str(archive)),
                        CommitOperationAdd(path_in_repo=f'checkpoints/{self.out.name}/latest.json',
                                           path_or_fileobj=json.dumps(proof,ensure_ascii=False).encode())],
                    commit_message=f'Checkpoint {self.out.name}: {proof["completed"]}/{proof["selected"]}',num_threads=1)
                return getattr(commit,'oid',str(commit))
            except Exception:
                if attempt==self.config['upload_attempts']: raise
                time.sleep(min(2**attempt,30))

    def maybe_save(self, *, new_completed=0, force=False):
        if not self.config['enabled']: return None
        self.observed += new_completed
        now = time.monotonic()
        due = self.observed-self.last_saved >= self.config['every_urls'] or now-self.last_time >= self.config['every_seconds']
        retry_upload = (self.config['upload'] and self.state.get('upload_status')=='failed'
                        and now-self.last_attempt >= self.config['failure_retry_seconds'])
        if not (force or due or retry_upload): return None
        failed_backup = self.state.get('local_status')=='failed' or self.state.get('upload_status')=='failed'
        if not force and failed_backup and now-self.last_attempt < self.config['failure_retry_seconds']: return None
        self.last_attempt = now
        try:
            archive, proof = self.build()
            self.last_saved, self.last_time = proof['completed'],time.monotonic()
            self.state = dict(proof, local_status='saved', upload_status='disabled', local_archive=str(archive))
            if self.config['upload']:
                try:
                    self.state.update(upload_status='uploaded',commit_sha=self.upload(archive,proof))
                except Exception as exc:
                    self.state.update(upload_status='failed',error=safe_error(exc,os.environ.get(self.config['token_env'],'')))
            self.crawler.write_json(self.state_path,self.state)
            print(json.dumps({'event':'periodic_checkpoint','completed':proof['completed'],'pending':proof['pending'],
                'local_archive':str(archive),'upload_status':self.state['upload_status'],
                'error':self.state.get('error')},ensure_ascii=False),flush=True)
            return self.state
        except Exception as exc:
            self.state.update(local_status='failed',error=safe_error(exc,os.environ.get(self.config['token_env'],'')))
            self.crawler.write_json(self.state_path,self.state)
            print(json.dumps({'event':'checkpoint_error','error':self.state['error']},ensure_ascii=False),flush=True)
            return self.state  # A backup service failure does not discard crawl progress.
