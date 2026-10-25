"""Archive local 4B progress to HF; preview by default. Stop the pipeline first."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from vibiomir.pipeline import run_lock


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(8*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', default='nguyen/pipeline_runs/hf_all_qwen4b_v1')
    p.add_argument('--repo', default='AncientWings/AncientWings_R2AI_STAGE3_ds')
    p.add_argument('--push', action='store_true')
    p.add_argument('--cleanup', action='store_true', help='Delete verified archived files locally, including this run; requires --push')
    p.add_argument('--discard-local-resume', action='store_true', help='Allow cleanup of an incomplete run: local pipeline cannot resume until archive is restored')
    a = p.parse_args()
    if a.cleanup and not a.push: p.error('--cleanup requires --push')
    run = (ROOT/a.run).resolve()
    if not run.is_relative_to((ROOT/'nguyen/pipeline_runs').resolve()) or run == (ROOT/'nguyen/pipeline_runs').resolve():
        raise ValueError('Run must be a child of nguyen/pipeline_runs')
    index = run/'index/qwen3-embedding-4b'
    cp = index/'embeddings.checkpoint.json'
    if not cp.is_file(): raise FileNotFoundError(cp)
    # Same OS lock as pipeline: never archive/delete while its writer is active.
    with run_lock(run/'pipeline.lock'):
        state = json.loads(cp.read_text(encoding='utf-8'))
        done = state['done']; total, dim = state['key']['shape']
        if not 0 < done <= total: raise ValueError('Invalid checkpoint')
        if a.cleanup and done < total and not a.discard_local_resume:
            raise ValueError('Incomplete run. Add --discard-local-resume only if moving work away from this laptop.')
        chunks=run/'chunks/chunks.parquet'
        if sha(chunks) != state['key']['input']: raise ValueError('Chunk checksum mismatch')
        identity=hashlib.sha256(json.dumps(state['key'],sort_keys=True).encode()).hexdigest()[:24]
        prefix=f'embeddings/local_qwen3_4b/{identity}/rows_0_{done}'
        files={f'run/{f.relative_to(run).as_posix()}':f for f in run.rglob('*')
               if f.is_file() and f.name not in ('pipeline.lock','embeddings.partial.npy','embeddings.npy')}
        snapshot=json.loads((run/'stages/hf_snapshot.json').read_text(encoding='utf-8'))
        snapshot_files=[]
        for raw,digest in snapshot['outputs'].items():
            f=Path(raw).resolve()
            if not f.is_relative_to((ROOT/'nguyen/hf_pipeline/snapshots').resolve()): raise ValueError('Unexpected snapshot path')
            if sha(f)!=digest: raise ValueError(f'Snapshot changed: {f}')
            files['snapshot/'+f.name]=f; snapshot_files.append(f)
        print(json.dumps(dict(repo=a.repo,remote=prefix,done=done,total=total,local=str(run),cleanup=a.cleanup),indent=2))
        if not a.push:
            print('Preview only. Stop pipeline, then use --push. No data deleted.'); return
        import numpy as np
        from huggingface_hub import HfApi,HfFileSystem,CommitOperationAdd,get_token
        token=get_token()
        if not token:
            token_path=ROOT/'nguyen/hf_pipeline/hf_home/token'
            if token_path.exists(): token=token_path.read_text().strip()
        if not token: raise ValueError('Run hf auth login with a writable token')
        api=HfApi(token=token); fs=HfFileSystem(token=token)
        api.dataset_info(a.repo)
        with tempfile.TemporaryDirectory(prefix='embedding_upload_',dir=run.parent) as temp:
            temp=Path(temp)
            source=index/('embeddings.npy' if (index/'embeddings.npy').exists() else 'embeddings.partial.npy')
            matrix=np.load(source,mmap_mode='r')
            if matrix.shape!=(total,dim) or matrix.dtype!=np.float16: raise ValueError('Unexpected vector matrix')
            vector=temp/'embeddings_completed.npy'
            dst=np.lib.format.open_memmap(vector,mode='w+',dtype=np.float16,shape=(done,dim))
            for start in range(0,done,1024):
                block=np.asarray(matrix[start:min(start+1024,done)],dtype=np.float32)
                if not np.isfinite(block).all() or not np.allclose(np.linalg.norm(block,axis=1),1,atol=.02):
                    raise ValueError('Invalid vectors')
                dst[start:start+len(block)]=block
            dst.flush(); del dst,matrix
            files['embeddings_completed.npy']=vector
            hashes={name:sha(f) for name,f in files.items()}
            manifest=temp/'archive_manifest.json'
            manifest.write_text(json.dumps(dict(format='local_4b_prefix_v1',key=state['key'],done=done,total=total,
                files=hashes,original_run=str(run),note='Vectors contain ONLY rows [0,done). Original checkpoint shape is total. Restore by creating a total-size float16 NPY memmap and copying these prefix rows; never rename prefix to full matrix.'),indent=2),encoding='utf-8')
            # Upload immutable objects separately; publish completion marker only after all hashes verify.
            remote_files=set(api.list_repo_files(a.repo,repo_type='dataset'))
            def remote_sha(name):
                h=hashlib.sha256()
                with fs.open(f'datasets/{a.repo}/{prefix}/{name}','rb',block_size=8*1024*1024) as stream:
                    for b in iter(lambda:stream.read(8*1024*1024),b''): h.update(b)
                return h.hexdigest()
            for name,f in files.items():
                remote=prefix+'/'+name
                if remote not in remote_files or remote_sha(name)!=hashes[name]:
                    api.upload_file(repo_id=a.repo,repo_type='dataset',path_in_repo=remote,path_or_fileobj=str(f))
                    fs.invalidate_cache()
                if remote_sha(name)!=hashes[name]: raise ValueError('Remote verification failed: '+name)
                print('Verified:',name,flush=True)
            api.upload_file(repo_id=a.repo,repo_type='dataset',path_in_repo=prefix+'/archive_manifest.json',path_or_fileobj=str(manifest))
            fs.invalidate_cache()
            if remote_sha('archive_manifest.json')!=sha(manifest): raise ValueError('Manifest verification failed')
            if a.cleanup:
                # Verify local files again before deletion; retain model cache and other runs.
                for name,f in files.items():
                    if f==vector: continue
                    if sha(f)!=hashes[name]: raise ValueError('Local file changed: '+str(f))
                # Snapshot may be shared by another run. Keep shared snapshot artifacts.
                shared=False
                for s in (ROOT/'nguyen/pipeline_runs').glob('*/stages/hf_snapshot.json'):
                    if not s.is_relative_to(run) and any(str(f) in s.read_text(encoding='utf-8').replace('\\\\','\\') for f in snapshot_files): shared=True
                for name,f in files.items():
                    if f==vector or (name.startswith('snapshot/') and shared): continue
                    f.unlink()
                source.unlink()
                print('Archived files removed. Model cache retained. Local resume requires restoring this archive.')
        print('HF archive:',f'https://huggingface.co/datasets/{a.repo}/tree/main/{prefix}')

if __name__=='__main__': main()
