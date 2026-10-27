"""Baseline versus extractive contextual embedding: fixed chunks, population and 0.6B models."""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ARMS = ('baseline', 'contextual', 'adjacent')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--arms', nargs='+', choices=list(ARMS), default=['contextual'])
    p.add_argument('--out', default='nguyen/pipeline_runs/embedding_comparison_0_50000')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    out = (ROOT/a.out).resolve()
    if not a.dry_run: out.mkdir(parents=True, exist_ok=True)
    reports = []
    reference = None
    # Existing completed arms remain part of the corpus consistency check on resume.
    for old in out.glob('*/stages/prepare.json'):
        digest = next(v for k,v in json.loads(old.read_text(encoding='utf-8'))['outputs'].items()
                      if Path(k).name == 'corpus.parquet')
        if reference is not None and reference != digest: raise ValueError('Existing arms have different corpora')
        reference = digest
    for name in a.arms:
        target, overlap = 320, 80
        run = out/name
        cmd = [sys.executable, '-X', 'utf8', '-u', str(ROOT/'scripts/vibiomir.py'), 'pipeline',
               '--source', 'hf', '--id-range', '0:50000', '--language', 'all', '--limit', '0',
               '--hf-max-shards', '0', '--skip-translation', '--encoders', 'qwen3-embedding-0.6b',
               '--rerankers', 'qwen3-reranker-0.6b', '--quantize', 'none', '--embedding-on-gpu',
               '--chunk-tokenizer', 'Qwen/Qwen3-Embedding-0.6B', '--model-max-length', '768',
               '--chunk-target', str(target), '--chunk-overlap', str(overlap),
               '--embedding-text', name,
               '--top-k', '300', '--fuse-k', '600', '--rerank-k', '50', '--keep', '25',
               '--out', str(run)]
        print('\nARM:',name,flush=True)
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
        report=dict(arm=name,corpus_sha256=digest,chunks_sha256=dense['chunks_sha256'],
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
