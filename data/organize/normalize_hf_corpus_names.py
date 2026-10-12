"""Rename old local-sync shards and all their artifacts to ids_<first>_<last>_synced.

Default: remote preview. --apply commits each rename atomically on HF.
--local-staging PATH previews/renames prepared local staging instead of HF.
Only snapshots produced by sync_local_corpus_to_hf.py are migrated automatically.
"""
import argparse
import copy
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import zipfile

from sync_local_corpus_to_hf import ROOT, REPO, canonical_run_name, read_json, write_json, sha_file, workspace_lock

LEGACY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]*_(\d+)_(\d+)_([0-9a-f]{20})$')


def artifact_paths(name):
    return [f'corpus/{name}.parquet', f'corpus_jsonl/{name}.jsonl',
            f'archives/{name}.zip', f'diagnostics/{name}_diagnostics.zip',
            f'manifests/{name}/notebook_manifest.json', f'manifests/{name}/upload_manifest.json']


def rename_plan(names, paths):
    """Check all collisions before preparing or committing any rename."""
    planned, destinations = [], set()
    paths = set(paths)
    for old in sorted(names):
        match = LEGACY.fullmatch(old)
        if not match:
            continue
        new = canonical_run_name(int(match[1]), int(match[2]))
        if new in destinations:
            raise ValueError(f'Two old runs would become {new}; resolve their contents first.')
        occupied = set(artifact_paths(new)) & paths
        occupied.update(p for p in paths if p.startswith(f'manifests/{new}/'))
        if occupied:
            raise ValueError(f'Destination already exists for {old}: {sorted(occupied)}')
        required = {f'corpus/{old}.parquet', f'manifests/{old}/notebook_manifest.json',
                    f'manifests/{old}/upload_manifest.json'}
        if not required <= paths:
            raise ValueError(f'Incomplete run {old}: missing {sorted(required - paths)}')
        unknown = {p for p in paths if p.startswith(f'manifests/{old}/')} - set(artifact_paths(old))
        if unknown:
            raise ValueError(f'Unrecognised manifests need review: {sorted(unknown)}')
        mapping = {a: b for a, b in zip(artifact_paths(old), artifact_paths(new)) if a in paths}
        planned.append((old, new, mapping))
        destinations.add(new)
    return planned


def rewrite_metadata(value, old, new, mapping):
    """Change run/path references, not free-form corpus text or parent run provenance."""
    if isinstance(value, dict):
        return {key: (new if key == 'run_name' and item == old else
                      rewrite_metadata(item, old, new, mapping)) for key, item in value.items()}
    if isinstance(value, list):
        return [rewrite_metadata(item, old, new, mapping) for item in value]
    if isinstance(value, str):
        return mapping.get(value, value)
    return value


def rewrite_zip(source, target, old, new, mapping):
    metadata_names = {'notebook_manifest.json', 'upload_manifest.json', 'hf_upload_manifest.json',
                      'hf_upload_result.json', 'summary.json'}
    seen = set()
    with zipfile.ZipFile(source) as reader, zipfile.ZipFile(target, 'w', allowZip64=True) as writer:
        for info in reader.infolist():
            parts = PurePosixPath(info.filename).parts
            if not parts or info.filename.startswith('/') or '..' in parts:
                raise ValueError(f'Unsafe ZIP member: {info.filename}')
            root = new if parts[0] == old else new + '_diagnostics' if parts[0] == old + '_diagnostics' else parts[0]
            renamed = '/'.join((root, *parts[1:])) + ('/' if info.is_dir() else '')
            if renamed in seen:
                raise ValueError(f'Duplicate ZIP member: {renamed}')
            seen.add(renamed)
            output_info = copy.copy(info)
            output_info.filename = renamed
            if not info.is_dir() and PurePosixPath(info.filename).name in metadata_names:
                metadata = json.loads(reader.read(info).decode('utf-8'))
                metadata = rewrite_metadata(metadata, old, new, mapping)
                if (PurePosixPath(info.filename).name == 'notebook_manifest.json'
                        and isinstance(metadata, dict)
                        and metadata.get('generated_by') == 'sync_local_corpus_to_hf.py'):
                    metadata['run_name'] = new
                writer.writestr(output_info, json.dumps(metadata,
                                                       ensure_ascii=False, indent=2).encode('utf-8'))
            else:
                # Stream corpus/raw without loading an entire archive into memory.
                with reader.open(info) as src, writer.open(output_info, 'w', force_zip64=True) as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)


def prepare_rename(old, new, mapping, load, output):
    """Return changed small metadata/ZIP files; Parquet/JSONL retain their original bytes."""
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = f'manifests/{old}/notebook_manifest.json'
    proof_path = f'manifests/{old}/upload_manifest.json'
    manifest, proof = read_json(load(manifest_path)), read_json(load(proof_path))
    if manifest.get('generated_by') != 'sync_local_corpus_to_hf.py' or proof.get('run_name') != old:
        raise ValueError(f'{old}: not a recognised local-sync snapshot.')
    if canonical_run_name(manifest['id_from_inclusive'], manifest['id_to_inclusive']) != new:
        raise ValueError(f'{old}: filename ID range differs from manifest.')
    if (proof.get('id_from_inclusive'), proof.get('id_to_inclusive')) != (
            manifest['id_from_inclusive'], manifest['id_to_inclusive']):
        raise ValueError(f'{old}: upload manifest ID range mismatch.')
    entries = {f['path_in_repo']: f for f in proof['files']}
    if len(entries) != len(proof['files']) or set(entries) != set(mapping) - {proof_path}:
        raise ValueError(f'{old}: upload manifest file list differs from actual artifacts.')
    changed = {}
    for before, after in mapping.items():
        if before == proof_path or before.startswith(('corpus/', 'corpus_jsonl/')):
            continue
        source = Path(load(before))
        if sha_file(source) != entries[before]['sha256'] or source.stat().st_size != entries[before]['bytes']:
            raise ValueError(f'Artifact hash/size mismatch: {before}')
        destination = output / PurePosixPath(after).name
        if before.endswith('.zip'):
            rewrite_zip(source, destination, old, new, mapping)
        else:
            metadata = rewrite_metadata(read_json(source), old, new, mapping)
            metadata['run_name'] = new
            write_json(destination, metadata)
        changed[after] = destination
    proof = rewrite_metadata(proof, old, new, mapping)
    for item in proof['files']:
        if item['path_in_repo'] in changed:
            path = changed[item['path_in_repo']]
            item.update(bytes=path.stat().st_size, sha256=sha_file(path))
    destination = output / 'upload_manifest.json'
    write_json(destination, proof)
    changed[mapping[proof_path]] = destination
    return changed


def local_filename(remote):
    if remote.startswith('corpus/'):
        return 'corpus.parquet'
    if remote.startswith('corpus_jsonl/'):
        return 'corpus.jsonl'
    return PurePosixPath(remote).name


def local_mode(args, out):
    staging = args.local_staging.resolve()
    if not staging.is_dir():
        raise ValueError(f'Staging directory missing: {staging}')
    names, paths = [], set()
    for folder in staging.iterdir():
        if folder.is_dir():
            names.append(folder.name)
            paths.update(p for p in artifact_paths(folder.name) if (folder / local_filename(p)).is_file())
    plans = rename_plan(names, paths)
    # A destination directory is also a collision even when it has no artifacts yet.
    for _old, new, _mapping in plans:
        if (staging / new).exists():
            raise ValueError(f'Local destination exists: {staging / new}')
    prepared = []
    for old, new, mapping in plans:
        print(f'{old} -> {new}', flush=True)
        loader = lambda p, folder=staging / old: folder / local_filename(p)
        changes = prepare_rename(old, new, mapping, loader, out / 'prepared' / new)
        prepared.append((old, new, mapping, changes))
    write_json(out / 'local_rename_plan.json', [{'old': a, 'new': b, 'paths': c} for a, b, c in plans])
    if args.apply:
        for old, new, mapping, changes in prepared:
            source, target = staging / old, staging / new
            # Keep the old staging directory as backup; never touch crawler output/HF cache.
            target.mkdir()
            for before, after in mapping.items():
                src = changes.get(after, source / local_filename(before))
                shutil.copy2(src, target / local_filename(after))
        print('Normalised staging copies created; original staging folders retained as backup.')
    else:
        print('Local preview only; use --apply to create normalised staging copies.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-id', default=REPO)
    parser.add_argument('--out', type=Path, default=ROOT / 'work/hf_name_normalization')
    parser.add_argument('--apply', action='store_true', help='Apply renames; default prepares a preview only.')
    parser.add_argument('--local-staging', type=Path, help='Normalise local staging copies instead of HF.')
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    with workspace_lock(out):
        if args.local_staging:
            if out.is_relative_to(args.local_staging.resolve()):
                raise ValueError('--out must be outside --local-staging.')
            local_mode(args, out)
            return
        from huggingface_hub import HfApi, CommitOperationAdd, CommitOperationCopy, CommitOperationDelete, hf_hub_download, get_token
        token = os.environ.get('HF_TOKEN') or get_token()
        if not token:
            raise RuntimeError('Run hf auth login or set HF_TOKEN.')
        api = HfApi(token=token)
        revision = api.repo_info(repo_id=args.repo_id, repo_type='dataset', revision='main').sha
        paths = set(api.list_repo_files(repo_id=args.repo_id, repo_type='dataset', revision=revision))
        names = {PurePosixPath(p).stem for p in paths if p.startswith('corpus/') and p.endswith('.parquet')}
        plans = rename_plan(names, paths)
        report = {'repo_id': args.repo_id, 'source_revision': revision, 'renames': [], 'commits': []}
        def load(path):
            return hf_hub_download(repo_id=args.repo_id, repo_type='dataset', revision=revision,
                                   filename=path, token=token, cache_dir=str(out / 'hf_cache'))
        prepared = []
        for old, new, mapping in plans:
            print(f'{old} -> {new}', flush=True)
            changes = prepare_rename(old, new, mapping, load, out / 'prepared' / new)
            prepared.append((old, new, mapping, changes))
            report['renames'].append({'old': old, 'new': new, 'paths': mapping})
        report_path = out / 'rename_result.json'
        write_json(report_path, report)
        if not args.apply:
            print(f'Preview: {len(plans)} runs; no HF changes. Review {report_path}; use --apply to rename.')
            return
        parent = revision
        for old, new, mapping, changes in prepared:
            operations = []
            for before, after in mapping.items():
                if after in changes:
                    operations.append(CommitOperationAdd(path_in_repo=after, path_or_fileobj=str(changes[after])))
                else:
                    operations.append(CommitOperationCopy(src_path_in_repo=before, path_in_repo=after,
                                                          src_revision=revision))
                operations.append(CommitOperationDelete(path_in_repo=before))
            # Copy/add and remove old names in one atomic commit, guarded against concurrent writes.
            commit = api.create_commit(repo_id=args.repo_id, repo_type='dataset', revision='main',
                parent_commit=parent, operations=operations, commit_message=f'Rename {old} to {new}')
            parent = commit.oid
            report['commits'].append({'old': old, 'new': new, 'oid': commit.oid, 'url': commit.commit_url})
            write_json(report_path, report)
            print(commit.commit_url, flush=True)
        print(f'Done: {len(plans)} runs renamed. {report_path}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        message = str(error)
        if os.environ.get('HF_TOKEN'):
            message = message.replace(os.environ['HF_TOKEN'], '[TOKEN]')
        message = re.sub(r'\bhf_[A-Za-z0-9]{8,}\b', '[TOKEN]', message)
        message = re.sub(r'(https?://[^\s?]+)\?\S+', r'\1?[QUERY]', message)
        print(f'ERROR: {type(error).__name__}: {message}', file=sys.stderr)
        print('If HF changed or the response was lost, rerun to rebuild the plan. Completed renames are preserved.', file=sys.stderr)
        raise SystemExit(1)
