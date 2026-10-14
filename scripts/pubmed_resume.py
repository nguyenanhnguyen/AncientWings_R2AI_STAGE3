"""Upgrade only the compatible EFetch transport, preserving existing XML and all data checkpoints."""
import ast
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import time
from urllib.parse import urlsplit

PARSER_FUNCTIONS = ('xml_text', 'extract_record', 'parse_efetch')


def sha(data): return hashlib.sha256(data).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def atomic(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_bytes(body)
    temp.replace(path)
def write(path, value): atomic(path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())


def parser_contract(body):
    tree = ast.parse(body.decode('utf-8'))
    functions = {n.name: ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,ast.FunctionDef)}
    if not all(name in functions for name in PARSER_FUNCTIONS): raise ValueError('Missing EFetch XML parser contract.')
    return {name:functions[name] for name in PARSER_FUNCTIONS}


def load_api(path):
    spec = importlib.util.spec_from_file_location('resume_efetch',path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_data(out, api):
    """Read-only verification, including cached records that are not reprocessed during resume."""
    out = Path(out)
    manifest = read(out/'manifest.json')
    body = (out/'sample.jsonl').read_bytes()
    if sha(body)!=manifest['sample_sha256']: raise ValueError('Resume sample hash mismatch.')
    samples = [json.loads(line) for line in body.decode('utf-8').split('\n') if line.strip()]
    by_id = {s['id']:s for s in samples}
    if len(by_id)!=len(samples) or len(samples)!=manifest['selected']: raise ValueError('Resume sample IDs/count mismatch.')
    pmids = {api.pmid_from_url(s['url']) for s in samples if urlsplit(s['url']).hostname=='pubmed.ncbi.nlm.nih.gov'}
    raw_cache, api_records = {}, {}
    def evidence(record):
        path = (out/record['raw_path']).resolve()
        if not path.is_relative_to((out/'raw').resolve()): raise ValueError('Resume raw path outside run.')
        if path not in raw_cache:
            with gzip.open(path,'rb') as stream: raw=stream.read(api.MAX_RESPONSE_BYTES+1)
            if len(raw)>api.MAX_RESPONSE_BYTES: raise ValueError('Resume XML exceeds size limit.')
            checksum=sha(raw)
            if checksum!=record['raw_sha256']: raise ValueError('Resume raw hash mismatch.')
            raw_cache[path] = (checksum,api.parse_efetch(raw,pmids)[0])
        checksum, documents = raw_cache[path]
        if checksum!=record['raw_sha256']: raise ValueError('Resume raw hash mismatch.')
        return documents
    def validate_mapping(record):
        sample=by_id.get(record.get('id'))
        if sample is None or sample['url']!=record.get('url'): raise ValueError('Resume checkpoint ID/URL mismatch.')
        if 'text' in record and sha(record['text'].encode())!=record.get('text_sha256'):
            raise ValueError('Resume text hash mismatch.')
        return sample
    for path in (out/'pubmed_records').glob('*.json'):
        record=read(path)
        if path.stem!=str(record.get('id')): raise ValueError('Resume API checkpoint filename/ID mismatch.')
        sample=validate_mapping(record)
        pmid=api.pmid_from_url(sample['url'])
        if record.get('engine')!='efetch' or record.get('http_status')!=200 or record.get('pubmed_pmid')!=pmid:
            raise ValueError('Resume API record is not a completed EFetch result.')
        documents=evidence(record)
        doc=documents.get(pmid)
        if record.get('pubmed_api_status')=='missing_pmid':
            if doc is not None or record.get('text'): raise ValueError('Resume missing-PMID evidence mismatch.')
        elif doc is None or doc['text']!=record.get('text') or doc['title']!=record.get('title'):
            raise ValueError('Resume PMID/XML text mismatch.')
        api_records[record['id']]=record
    canonical=0
    for path in (out/'records').glob('*.json'):
        record=read(path)
        if path.stem!=str(record.get('id')): raise ValueError('Resume canonical checkpoint filename/ID mismatch.')
        validate_mapping(record)
        if record.get('engine')=='efetch':
            reference=api_records.get(record['id'])
            if reference is None or any(record.get(k)!=reference.get(k) for k in ('text','url','raw_sha256','text_sha256')):
                raise ValueError('Resume canonical/API checkpoint mismatch.')
        canonical+=1
    for path in (out/'pubmed_batches').glob('*.json'):
        batch=read(path)
        if batch.get('version')!=api.VERSION: raise ValueError('Resume XML batch version incompatible.')
        for sample in batch['samples']:
            if by_id.get(sample['id'])!=sample: raise ValueError('Resume batch ID/URL mismatch.')
        evidence(batch)
    return {'selected':len(samples),'completed':canonical,'pending':len(samples)-canonical,
            'pubmed_completed':len(api_records),'xml_raw_verified':len(raw_cache)}


def upgrade(out, new_body, config, *, enabled=True):
    """Journal code/config as a recoverable pair; never write records/raw/batches/source manifests."""
    out=Path(out)
    target=out/'pubmed_efetch_snapshot.py'
    identity_path=out/'corpus_config.json'
    if not enabled:
        return {'status':'disabled'}
    if not identity_path.exists():
        if (out/'records').exists() and any((out/'records').glob('*.json')):
            raise ValueError('Cannot upgrade a legacy run without corpus_config.json; use recovery.')
        atomic(target,new_body)
        return {'status':'new_run'}
    journal_path=out/'pubmed_upgrade_journal.json'
    journal=read(journal_path) if journal_path.exists() else {}
    if journal.get('status')=='running':
        if journal['new_sha256']!=sha(new_body): raise ValueError('Interrupted upgrade targets different EFetch code.')
        identity=journal['previous_identity']
        if read(identity_path) not in (identity,journal['new_identity']):
            raise ValueError('Interrupted upgrade configuration changed unexpectedly.')
        old_body=(out/journal['old_code_path']).read_bytes()
        if sha(target.read_bytes()) not in (journal['old_sha256'],journal['new_sha256']):
            raise ValueError('Interrupted upgrade EFetch snapshot changed unexpectedly.')
    else:
        identity=read(identity_path)
        old_body=target.read_bytes()
        if sha(old_body)!=identity.get('pubmed_efetch_sha256'): raise ValueError('Saved EFetch snapshot hash mismatch.')
    if identity['settings'].get('pubmed_use_efetch') is not True:
        raise ValueError('Transport upgrade only supports existing EFetch runs.')
    for name,key in [('crawler_snapshot.py','crawler_sha256'),('corpus_runner_snapshot.py','runner_sha256'),
                     ('priority_probe_snapshot.py','probe_sha256')]:
        if sha((out/name).read_bytes())!=identity[key]: raise ValueError('Unchanged runtime snapshot hash mismatch: '+name)
    if parser_contract(old_body)!=parser_contract(new_body):
        raise ValueError('XML parser changed; use a new recovery run, not a transport-only upgrade.')
    # Load the new code without first replacing the saved transport. Its companion checkpoint helper is refreshed.
    candidate=out/'snapshot_history'/f'efetch_candidate_{sha(new_body)}.py'
    atomic(candidate,new_body)
    # validate_config loads checkpoint_snapshot.py relative to the module; use the verified run helper there too.
    helper=out/'checkpoint_snapshot.py'
    atomic(candidate.parent/'checkpoint_snapshot.py',helper.read_bytes())
    api=load_api(candidate)
    config=api.validate_config(config)
    state=validate_data(out,api)
    new_identity=dict(identity,settings=dict(identity['settings'],pubmed_efetch=config),pubmed_efetch_sha256=sha(new_body))
    if sha(target.read_bytes())==sha(new_body) and read(identity_path)==new_identity:
        return dict(state,status='current',transport_version=api.TRANSPORT_VERSION)
    old_path=f'snapshot_history/efetch_{sha(old_body)}.py'
    atomic(out/old_path,old_body)
    write(out/'snapshot_history'/f'corpus_config_{sha(json.dumps(identity,sort_keys=True).encode())}.json',identity)
    journal=dict(status='running',old_sha256=sha(old_body),new_sha256=sha(new_body),old_code_path=old_path,
                 previous_identity=identity,new_identity=new_identity,progress_verified=state)
    write(journal_path,journal)
    atomic(target,new_body)
    write(identity_path,new_identity)
    journal['status']='complete'
    write(journal_path,journal)
    return dict(state,status='upgraded',transport_version=api.TRANSPORT_VERSION)


def runtime_settings(out, desired):
    """Retain the saved non-PubMed route/config; only the HTTP resilience settings are upgraded."""
    path=Path(out)/'corpus_config.json'
    if not path.exists(): return desired
    saved=read(path)['settings']
    for key,value in saved.items():
        if key!='pubmed_efetch' and key in desired and desired[key]!=value:
            raise ValueError('Non-EFetch config changed during resume: '+key+'; use a new recovery run.')
    result=dict(saved,pubmed_efetch=desired['pubmed_efetch'])
    # The snapshot upgrader already validated/normalized the proposed EFetch settings.
    result['pubmed_efetch']=saved['pubmed_efetch']
    return result
