"""Download the inputs of one run from Hugging Face: the team's crawled corpus and BTC's files.

Both the laptop and the Kaggle notebook start here, so they process the same data the same way.

    corpus   `corpus/*.parquet` of the team dataset (AncientWings/AncientWings_R2AI_STAGE3_ds),
             written by the crawl notebooks and `sync_local_corpus_to_hf.py`. Read at one commit.
    BTC      `query.parquet` and `links_corpus.parquet` of AIGuruTinix/ViBioMIR at a fixed
             revision; links_corpus is checked against its published SHA-256.

The corpus commit is resolved once and pinned in the run directory (`pinned.json`). Re-running the
same run, after an interruption or on another day, keeps reading that commit even when teammates
have pushed more data since; new data means a new run directory. Files go into a folder named
after the commit, so two commits can never mix. Downloads resume: huggingface_hub skips files
already present and complete.

Private datasets need a token: `hf auth login` once on the laptop, or the HF_TOKEN secret on
Kaggle. huggingface_hub finds either on its own.
"""
import argparse
import json
from pathlib import Path
import re
import sys

from ..common import storage
from ..common.console import emit
from .prepare import add_id_arguments, validate_id_range

CORPUS_REPO = 'AncientWings/AncientWings_R2AI_STAGE3_ds'
SOURCE_REPO = 'AIGuruTinix/ViBioMIR'
SOURCE_REVISION = '0148f6f80ffafed5c005af6d506ccfd9d3fb47a7'
LINKS_SHA256 = 'dee1153f5b9d9010dea18e1b7724b4915ff847b711d036bec8b933486802a971'


def layout(out, revision):
    """Paths of one fetched snapshot inside `out`."""
    out = Path(out)
    return {'corpus': out / f'corpus_{revision[:12]}' / 'corpus',
            'queries': out / 'source' / 'query.parquet',
            'links': out / 'source' / 'links_corpus.parquet',
            'manifest': out / 'fetch_manifest.json',
            'pin': out / 'pinned.json'}


def resolve_revision(out, repo=CORPUS_REPO, requested=None):
    """The corpus commit for this run: the pinned one, else `requested`, else the latest.

    Raises when a run already pinned one commit and another is requested: mixing two snapshots in
    one run would change the corpus under finished stages.
    """
    pin = layout(out, 'x')['pin']
    if pin.exists():
        pinned = storage.read_json(pin)
        if pinned['repo'] != repo or (requested and not pinned['revision'].startswith(requested)):
            raise ValueError(f"This run is pinned to {pinned['repo']}@{pinned['revision'][:12]}; "
                             'use a new --out for another repository or commit.')
        return pinned['revision']
    if requested and len(requested) == 40:
        return requested
    from huggingface_hub import HfApi
    return HfApi().dataset_info(repo, revision=requested).sha


def pin(out, repo, revision):
    path = layout(out, revision)['pin']
    if not path.exists():
        storage.write_json(path, {'repo': repo, 'revision': revision})


def select_shards(names, id_start=None, id_end=None):
    """Prune only canonical, disjoint ranges; unknown names need row-level filtering."""
    validate_id_range(id_start, id_end)
    selected = []
    for name in sorted(names):
        if not name.startswith('corpus/') or name.count('/') != 1 or not name.endswith('.parquet'):
            continue
        match = re.fullmatch(r'corpus/ids_(\d+)_(\d+)_synced\.parquet', name)
        if match:
            lo, hi = map(int, match.groups())
            if lo <= hi and ((id_start is not None and hi < id_start)
                             or (id_end is not None and lo > id_end)):
                continue
        selected.append(name)
    return selected


def pin_selection(out, id_start=None, id_end=None):
    """Even an interrupted download must not later mix a different ID selection."""
    validate_id_range(id_start, id_end)
    path = Path(out) / 'selection.json'
    selection = {'id_start': id_start, 'id_end': id_end}
    if path.exists() and storage.read_json(path) != selection:
        raise ValueError('HF ID range is pinned for this run; use a new --out.')
    if not path.exists():
        # A legacy download selected every shard; don't narrow it in place.
        if (Path(out) / 'fetch_manifest.json').exists() and any(x is not None for x in selection.values()):
            raise ValueError('Legacy HF snapshot has no ID range; use a new --out.')
        storage.write_json(path, selection)


def fetch(args):
    from huggingface_hub import hf_hub_download, snapshot_download
    import pyarrow.parquet as pq

    id_start, id_end = getattr(args, 'id_start', None), getattr(args, 'id_end', None)
    pin_selection(args.out, id_start, id_end)
    paths = layout(args.out, args.revision)
    paths['queries'].parent.mkdir(parents=True, exist_ok=True)
    for name in ('query.parquet', 'links_corpus.parquet'):
        hf_hub_download(SOURCE_REPO, name, repo_type='dataset', revision=SOURCE_REVISION,
                        local_dir=paths['queries'].parent)
    links_sha = storage.sha256_file(paths['links'])
    if links_sha != LINKS_SHA256:
        raise ValueError(f'links_corpus.parquet SHA-256 {links_sha} differs from the pinned '
                         'BTC release; refusing to build a submission on other ids.')
    patterns = ['corpus/*.parquet']
    if id_start is not None or id_end is not None:
        from huggingface_hub import HfApi
        names = HfApi().list_repo_files(args.repo, repo_type='dataset', revision=args.revision)
        patterns = select_shards(names, id_start, id_end)
        if not patterns:
            raise ValueError('No HF corpus shard overlaps the requested ID range.')
        emit(f'fetch: {len(patterns)} shards overlap IDs [{id_start}, {id_end}]; '
             'prepare will filter exact row IDs before applying --limit.')
    snapshot_download(args.repo, repo_type='dataset', revision=args.revision,
                      allow_patterns=patterns, local_dir=paths['corpus'].parent)
    files = sorted(paths['corpus'].glob('*.parquet'))
    if not files:
        raise ValueError(f'{args.repo}@{args.revision[:12]} has no corpus/*.parquet.')
    rows = sum(pq.ParquetFile(path).metadata.num_rows for path in files)
    summary = {'corpus_repo': args.repo, 'corpus_revision': args.revision,
               'id_start': id_start, 'id_end': id_end,
               'selected_files': [p.name for p in files],
               'corpus_files': len(files), 'corpus_rows': rows, 'corpus_dir': str(paths['corpus']),
               'source_repo': SOURCE_REPO, 'source_revision': SOURCE_REVISION,
               'queries': str(paths['queries']), 'links': str(paths['links']),
               'queries_rows': pq.ParquetFile(paths['queries']).metadata.num_rows}
    storage.write_manifest(paths['manifest'], summary, files=[paths['queries'], paths['links']])
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


AUTH_HELP = ('Hugging Face từ chối truy cập (401/404). Dataset corpus của nhóm là private: '
             'trên laptop chạy `hf auth login` với token có quyền đọc AncientWings '
             '(hoặc đặt biến môi trường HF_TOKEN); trên Kaggle thêm Secret HF_TOKEN.')


def explain_auth(error):
    """A readable error for the common case: a missing or expired token."""
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    if status in (401, 403, 404) or 'Repository Not Found' in str(error):
        return RuntimeError(f'{AUTH_HELP}\nChi tiết: {str(error).splitlines()[0]}')
    return error


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', default='work/hf')
    parser.add_argument('--repo', default=CORPUS_REPO)
    add_id_arguments(parser)
    parser.add_argument('--revision', default=None,
                        help='Corpus commit; default: the pinned one, else the latest.')
    args = parser.parse_args()
    try:
        args.revision = resolve_revision(args.out, args.repo, args.revision)
        pin(args.out, args.repo, args.revision)
        fetch(args)
    except Exception as error:
        raise explain_auth(error) from error


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
