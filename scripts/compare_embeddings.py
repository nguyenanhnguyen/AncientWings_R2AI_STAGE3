"""Baseline versus extractive contextual embedding: fixed chunks, population and 0.6B models."""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import os

ROOT = Path(__file__).resolve().parents[1]
ARMS = ('baseline', 'contextual', 'adjacent')


def balanced_source(out):
    """Freeze 20k valid documents per language once, reuse exact rows thereafter."""
    import hashlib
    import pyarrow.parquet as pq
    from huggingface_hub import HfApi, get_token
    directory = out/'dataset'
    directory.mkdir(parents=True, exist_ok=True)
    token = get_token()
    if not token:
        cached = ROOT/'nguyen/hf_pipeline/hf_home/token'
        if cached.exists(): token = cached.read_text().strip()
    if not token: raise ValueError('Authenticate with hf auth login first')
    os.environ['HF_TOKEN'] = token
    spec_path = directory/'selection.json'
    repo = 'AncientWings/AncientWings_R2AI_STAGE3_ds'
    if spec_path.exists():
        spec = json.loads(spec_path.read_text(encoding='utf-8'))
    else:
        spec = {'repo': repo, 'revision': HfApi(token=token).dataset_info(repo).sha,
                'per_language': 20000,
                'ranges': {'vi': '0:766443', 'zh': '766444:4392214',
                           'en': '4421055:7466161'}}
        spec_path.write_text(json.dumps(spec, indent=2), encoding='utf-8')
    target = directory/'balanced_60000.parquet'
    manifest = directory/'balanced_manifest.json'
    def digest(path):
        h = hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda: f.read(8*1024*1024), b''): h.update(block)
        return h.hexdigest()
    if manifest.exists():
        saved = json.loads(manifest.read_text(encoding='utf-8'))
        for name, expected in saved['files'].items():
            if digest(directory/name) != expected: raise ValueError('Frozen dataset changed: '+name)
        return target, directory/'vi/query.parquet', directory/'vi/links_corpus_vi_en_zh.parquet'
    for lang, interval in spec['ranges'].items():
        subprocess.run([sys.executable, '-X', 'utf8', '-u', str(ROOT/'scripts/vibiomir.py'),
            'hf-snapshot', '--repo', spec['repo'], '--revision', spec['revision'],
            '--language', lang, '--id-range', interval, '--limit', '20000',
            '--sample-mode', 'bounded', '--max-shards', '0', '--out', str(directory/lang)],
            cwd=ROOT, check=True)
    temporary = target.with_suffix('.partial.parquet')
    ids = {}; seen = set()
    writer = None
    try:
        for lang in spec['ranges']:
            path = directory/lang/f'input_{lang}.parquet'
            parquet = pq.ParquetFile(path)
            if parquet.metadata.num_rows != 20000: raise ValueError('Expected exactly 20000 '+lang)
            if writer is None: writer = pq.ParquetWriter(temporary, parquet.schema_arrow, compression='zstd')
            ids[lang] = []
            for batch in parquet.iter_batches(batch_size=2048):
                values = batch.column(batch.schema.get_field_index('id')).to_pylist()
                if any(v in seen for v in values): raise ValueError('Duplicate ID across language subsets')
                seen.update(values); ids[lang].extend(values)
                writer.write_batch(batch)
        writer.close(); writer = None
        os.replace(temporary, target)
    finally:
        if writer: writer.close()
    (directory/'selected_ids.json').write_text(json.dumps(ids), encoding='utf-8')
    files = [target, directory/'selected_ids.json', spec_path]
    files += [directory/lang/name for lang in spec['ranges']
              for name in ('query.parquet', 'links_corpus_vi_en_zh.parquet')]
    manifest.write_text(json.dumps({'spec': spec, 'counts': {k:len(v) for k,v in ids.items()},
        'files': {f.relative_to(directory).as_posix():digest(f) for f in files}}, indent=2), encoding='utf-8')
    return target, directory/'vi/query.parquet', directory/'vi/links_corpus_vi_en_zh.parquet'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--arms', nargs='+', choices=list(ARMS), default=['contextual'])
    p.add_argument('--out', default='nguyen/pipeline_runs/embedding_comparison_0_50000')
    p.add_argument('--id-range', action='append', default=None,
                   help='Inclusive START:END; repeat to combine official ID intervals.')
    p.add_argument('--require-contextual', action='store_true',
                   help='Require a completed contextual reference before running adjacent.')
    p.add_argument('--balanced20k', action='store_true',
                   help='Freeze exactly 20000 valid HF records per language once.')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    ranges = a.id_range or ['0:50000']
    for value in ranges:
        start, end = map(int, value.split(':'))
        if not 0 <= start <= end:
            p.error('Invalid inclusive ID interval')
    out = (ROOT/a.out).resolve()
    if not a.dry_run: out.mkdir(parents=True, exist_ok=True)
    if a.balanced20k and a.id_range:
        p.error('--balanced20k defines its own language search ranges; omit --id-range')
    source = None
    if a.balanced20k:
        source = ((out/'dataset/balanced_60000.parquet', out/'dataset/vi/query.parquet',
                   out/'dataset/vi/links_corpus_vi_en_zh.parquet') if a.dry_run else balanced_source(out))
    reports = []
    reference = None
    # Existing completed arms remain part of the corpus consistency check on resume.
    for old in out.glob('*/stages/prepare.json'):
        digest = next(v for k,v in json.loads(old.read_text(encoding='utf-8'))['outputs'].items()
                      if Path(k).name == 'corpus.parquet')
        if reference is not None and reference != digest: raise ValueError('Existing arms have different corpora')
        reference = digest
    for name in a.arms:
        if name == 'adjacent' and a.require_contextual and not a.dry_run:
            if not (out/'contextual/comparison.json').is_file() or not (out/'contextual/submission/submission.zip').is_file():
                raise ValueError('Complete contextual and retain its report/ZIP before adjacent.')
        target, overlap = 320, 80
        run = out/name
        cmd = [sys.executable, '-X', 'utf8', '-u', str(ROOT/'scripts/vibiomir.py'), 'pipeline',
               '--source', 'hf', *[x for interval in ranges for x in ('--id-range', interval)],
               '--language', 'all', '--limit', '0',
               '--hf-max-shards', '0', '--skip-translation', '--encoders', 'qwen3-embedding-0.6b',
               '--rerankers', 'qwen3-reranker-0.6b', '--quantize', 'none', '--embedding-on-gpu',
               '--chunk-tokenizer', 'Qwen/Qwen3-Embedding-0.6B', '--model-max-length', '768',
               '--chunk-target', str(target), '--chunk-overlap', str(overlap),
               '--embedding-text', name,
               '--top-k', '300', '--fuse-k', '600', '--rerank-k', '50', '--keep', '25',
               '--out', str(run)]
        print('\nARM:',name,flush=True)
        if source:
            start = cmd.index('--source')
            end = cmd.index('--hf-max-shards')
            cmd[start:end] = ['--source', str(source[0]), '--queries', str(source[1]),
                              '--links', str(source[2]), '--limit', '0']
        if a.dry_run: cmd.append('--dry-run')
        subprocess.run(cmd,cwd=ROOT,check=True)
        if a.dry_run: continue
        def read(path): return json.loads(path.read_text(encoding='utf-8'))
        stages={f.stem:read(f) for f in (run/'stages').glob('*.json')}
        digest=next(v for k,v in stages['prepare']['outputs'].items() if Path(k).name=='corpus.parquet')
        if reference is not None and reference!=digest: raise ValueError('Corpus differs: do not compare these scores')
        reference=digest
        chunks=read(run/'chunks/chunk_manifest.json')
        dense=read(run/'index/qwen3-embedding-0.6b/dense_manifest.json')
        retrieval=read(run/'retrieval/retrieval_manifest.json')
        report=dict(arm=name,id_ranges=None if a.balanced20k else ranges,
                    balanced20k=a.balanced20k,
                    prepared_languages=read(run/'corpus/prepare_manifest.json')['languages'],
                    corpus_sha256=digest,chunks_sha256=dense['chunks_sha256'],
                    queries_sha256=retrieval['queries_sha256'],
                    embedding_text=dense.get('embedding_text'),
                    chunks=chunks['chunks'],target=target,overlap=overlap,
                    embedding_model=dense['model'],reranker_models=retrieval['reranker_models'],
                    stage_seconds={k:v['seconds'] for k,v in stages.items() if 'seconds' in v},
                    vector_bytes=(run/'index/qwen3-embedding-0.6b/embeddings.npy').stat().st_size,
                    submission=str(run/'submission/submission.zip'))
        (run/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        reports.append(report)
    if not a.dry_run:
        # Compare pinned model identities across every completed arm, including prior sessions.
        completed=[json.loads(f.read_text(encoding='utf-8')) for f in out.glob('*/comparison.json')]
        if len({(r['corpus_sha256'],r['chunks_sha256'],r['queries_sha256']) for r in completed}) > 1:
            raise ValueError('Corpus/chunks/queries differ across runs; comparison is not controlled')
        identities={(r['embedding_model'].get('revision'),json.dumps(r['reranker_models'],sort_keys=True)) for r in completed}
        if len(identities)>1: raise ValueError('Model revisions/config differ across arms; comparison is not controlled')
        scorefile=out/'codabench_scores.csv'
        if not scorefile.exists():
            with scorefile.open('w',encoding='utf-8',newline='') as f:
                w=csv.writer(f);w.writerow(['arm','FINAL_SCORE','DOCS_F2MACRO','CHUNKS_F2MACRO','DOCS_PRECISION','DOCS_RECALL','CHUNKS_PRECISION','CHUNKS_RECALL'])
                for name in ARMS:w.writerow([name]+['']*7)
        else:
            with scorefile.open(encoding='utf-8', newline='') as f:
                present = {row['arm'] for row in csv.DictReader(f)}
            with scorefile.open('a', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                for name in ARMS:
                    if name not in present:
                        writer.writerow([name]+['']*7)
        print('Completed. Compare comparison.json and enter leaderboard scores in',scorefile)

if __name__=='__main__': main()
