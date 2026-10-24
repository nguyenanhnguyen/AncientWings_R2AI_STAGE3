"""Merge the fixed holdout workflow into the single 120ask check notebook."""
import argparse
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import zlib

import ask120_gate as gate

ROOT=Path(__file__).resolve().parents[1]
SAMPLE_PATH=ROOT/'docs/references/120ask/holdout_1000_20261020.json'


def validate_bundle(bundle):
    mapping=bundle['selected_mapping']
    rows={(str(r['id']),r['url']) for r in bundle['rows']}
    if len(mapping)!=1000 or not all((str(k),v) in rows and gate.PARSER.is_question_url(v) for k,v in mapping.items()):
        raise ValueError('Holdout mapping must match 1000 source questions')
    selected={gate.canonical_question(v) for v in mapping.values()}
    history={gate.canonical_question(r['url']) for r in bundle['history']}
    if len(selected)!=1000 or selected & history:
        raise ValueError('Holdout questions duplicate or overlap history')
    if {gate.canonical_question(r['url']) for r in bundle['rows']}!=selected:
        raise ValueError('Unexpected holdout source question')
    return bundle


def freeze_run(run):
    samples=gate.read_jsonl_bytes((run/'sample.jsonl').read_bytes())
    manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
    independence=json.loads((run/'sample_independence_audit.json').read_text(encoding='utf-8'))
    history={}
    for item in manifest['history_files']:
        path=Path(item['path'])
        if path.suffix.lower()=='.zip':
            reader=gate.RunInput(path)
            try: content=reader.read('sample.jsonl')
            finally: reader.close()
        else: content=path.read_bytes()
        if gate.sha(content)!=item['sha256']: raise ValueError('History hash changed: '+str(path))
        for row in gate.read_jsonl_bytes(content):
            url=row.get('source_url') or row.get('url')
            if url and gate.PARSER.is_question_url(url):
                history.setdefault(gate.canonical_question(url),dict(id=row['id'],url=url))
    return validate_bundle(dict(rows=[r for s in samples for r in s['source_aliases']],
        history=list(history.values()),independence=independence,
        selected_mapping={str(s['id']):s['url'] for s in samples}))


RUN_CELL="""
try:
    if MODE=='replay':
        samples=gate.replay(INPUT_PATH,RUN_DIR,POLICY)
    elif MODE=='holdout_1000':
        import requests
        from unittest.mock import patch
        class HoldoutAccessStopped(BaseException): pass
        _original_request=requests.sessions.Session.request
        _consecutive_errors=0
        def _guard_request(session,method,url,*args,**kwargs):
            global _consecutive_errors
            if _consecutive_errors>=5:raise HoldoutAccessStopped('5 lỗi truy cập liên tiếp')
            try:
                response=_original_request(session,method,url,*args,**kwargs)
            except requests.RequestException:
                _consecutive_errors+=1
                raise
            if response.status_code>=400:_consecutive_errors+=1
            elif 200<=response.status_code<300:_consecutive_errors=0
            return response
        try:
            with patch('requests.sessions.Session.request',new=_guard_request):
                samples=gate.crawl_new(SOURCE_PARQUET,RUN_DIR,POLICY,limit=LIMIT,seed=SEED,
                    history_paths=HISTORY_PATHS,support_dir=SUPPORT_DIR,delay=DELAY,attempts=ATTEMPTS,
                    timeout=(CONNECT_TIMEOUT,READ_TIMEOUT),budget=REQUEST_BUDGET,
                    trust_env=REQUESTS_TRUST_ENV,respect_robots=RESPECT_ROBOTS,stop_on_block=STOP_ON_BLOCK)
        except HoldoutAccessStopped as exc:
            print('DỪNG DO TRUY CẬP:',exc)
        actual={str(r['id']):r['url'] for r in gate.read_jsonl_bytes((RUN_DIR/'sample.jsonl').read_bytes())}
        if actual!=HOLDOUT['selected_mapping']:raise ValueError('Mẫu phải khớp đúng 1000 URL cố định')
    else:
        samples=gate.crawl_new(SOURCE_PARQUET,RUN_DIR,POLICY,limit=LIMIT,seed=SEED,
            history_paths=HISTORY_PATHS,support_dir=SUPPORT_DIR,
            delay=DELAY,attempts=ATTEMPTS,timeout=(CONNECT_TIMEOUT,READ_TIMEOUT),
            budget=REQUEST_BUDGET,trust_env=REQUESTS_TRUST_ENV,respect_robots=RESPECT_ROBOTS,
            stop_on_block=STOP_ON_BLOCK)
finally:
    if (RUN_DIR/'manifest.json').exists() and (RUN_DIR/'sample.jsonl').exists():
        summary=build_outputs()
"""


def integrate_holdout(notebook,bundle_bytes=None):
    """Pure, repeatable composition with one config/runtime/A-B section and ZIP."""
    if bundle_bytes is None:bundle_bytes=SAMPLE_PATH.read_bytes()
    validate_bundle(json.loads(bundle_bytes))
    encoded=base64.b85encode(zlib.compress(bundle_bytes,9)).decode('ascii')
    checksum=hashlib.sha256(bundle_bytes).hexdigest()
    nb=deepcopy(notebook)
    cells=[]
    previous={cell.get('id'):cell for cell in notebook['cells']}

    def extra(kind,source,id):
        result={'cell_type':kind,'id':id,'metadata':{},'source':(source.strip()+'\n').splitlines(keepends=True)}
        if kind=='code':
            compile(source,id,'exec');result.update(execution_count=None,outputs=[])
            prior=previous.get(id)
            if prior and prior.get('cell_type')=='code' and prior['source']==result['source']:
                result.update(execution_count=prior.get('execution_count'),outputs=deepcopy(prior.get('outputs',[])))
        return result

    for cell in nb['cells']:
        if cell.get('id','').startswith('ask120-holdout-'):continue
        text=''.join(cell['source'])
        if cell is nb['cells'][0]:
            text=text.replace('Tên file legacy giữ “50”, LIMIT hiện là 1.000.',
                'File chung cho replay, crawl_new và holdout_1000; LIMIT mặc định là 1.000.')
            if '## Chọn chế độ trong ô cấu hình' not in text:
                text+="""
## Chọn chế độ trong ô cấu hình

- MODE='replay': kiểm lại ZIP/thư mục raw cũ; mặc định, không gửi request.
- MODE='crawl_new': chọn mẫu từ SOURCE_PARQUET và loại HISTORY_PATHS.
- MODE='holdout_1000': chạy đúng 1.000 URL cố định, loại 1.086 câu hỏi lịch sử,
  không cần Parquet gốc; một worker, delay 2 giây, dừng sau 5 lỗi truy cập liên tiếp
  hoặc challenge/429, có audit/review packet riêng. Chế độ này cần Internet.

Sáu ô A/B dùng chung; mặc định chỉ bật khi replay vì holdout không có bộ regression cũ.
"""
        if cell['cell_type']=='code':
            text=text.replace("MODE = 'replay'  # replay | crawl_new\n",
                              "MODE = 'replay'  # replay | crawl_new | holdout_1000\n")
            text=text.replace("if MODE not in ('replay','crawl_new'):",
                              "if MODE not in ('replay','crawl_new','holdout_1000'):")
            text=text.replace('SEED = 20261020\n',"SEED = 2026102003 if MODE=='holdout_1000' else 20261020\n")
            text=text.replace('ATTEMPTS = 2\n',"ATTEMPTS = 1 if MODE=='holdout_1000' else 2\n")
            text=text.replace('RUN_EXPERIMENTS = True  # Offline A/B; cần replay đủ regression và EXPORT_CANDIDATE_CORPUS=True.',
                "RUN_EXPERIMENTS = MODE=='replay'  # A/B cần regression cũ; không bật mặc định cho holdout.")
            text=text.replace("if MODE=='crawl_new':\n","if MODE in ('crawl_new','holdout_1000'):\n")
            if 'INPUT_PATH=gate.locate_input' in text:
                bootstrap='HOLDOUT_PAYLOAD='+repr(encoded)+'\nHOLDOUT_SHA256='+repr(checksum)+"""
if MODE=='holdout_1000':
    import pyarrow as pa
    import pyarrow.parquet as pq
    _holdout_bytes=zlib.decompress(base64.b85decode(HOLDOUT_PAYLOAD))
    if hashlib.sha256(_holdout_bytes).hexdigest()!=HOLDOUT_SHA256:raise ValueError('Holdout hash mismatch')
    HOLDOUT=json.loads(_holdout_bytes)
    if len(HOLDOUT['selected_mapping'])!=LIMIT or LIMIT!=1000:raise ValueError('Holdout cần LIMIT=1000')
    SOURCE_PARQUET=RUN_DIR/'selected_holdout_source.parquet'
    pq.write_table(pa.Table.from_pylist(HOLDOUT['rows'],schema=pa.schema([('id',pa.int64()),('url',pa.string())])),SOURCE_PARQUET)
    HISTORY_FILE=RUN_DIR/'provided_history.jsonl'
    gate.jsonl(HISTORY_FILE,HOLDOUT['history'])
    HISTORY_PATHS=[HISTORY_FILE]
    gate.write_json(RUN_DIR/'original_sample_independence.json',HOLDOUT['independence'])
    print('Mẫu cố định:',LIMIT,'URL; lịch sử:',len(HOLDOUT['history']))
"""
                cells.append(extra('code',bootstrap,'ask120-holdout-bundle'))
            if 'samples=gate.crawl_new' in text:text=RUN_CELL
            if 'archive=Path(shutil.make_archive' in text:
                source=(ROOT/'scripts/ask120_holdout_audit.py').read_text(encoding='utf-8')
                source+="\nif MODE=='holdout_1000':\n    quality=audit(gate,RUN_DIR)\n    display(quality)\n"
                cells.append(extra('code',source,'ask120-holdout-audit'))
                text="""import shutil
archive=Path(shutil.make_archive(str(RUN_DIR),'zip',root_dir=RUN_DIR))
for name in ('holdout_quality_audit.json','holdout_review_packet.jsonl','summary.json','report.md',
             'regression_comparison.csv','corpus_decisions.csv','manual_review_sheet.csv',
             'corpus_candidates.jsonl','corpus_candidates.parquet'):
    if (RUN_DIR/name).exists():display(FileLink(str(RUN_DIR/name)))
display(FileLink(str(archive)))
"""
            compile(text,cell.get('id','unified'),'exec')
        if text!=''.join(cell['source']) and cell['cell_type']=='code':cell.update(execution_count=None,outputs=[])
        cell['source']=text.splitlines(keepends=True)
        cells.append(cell)
    cells.append(extra('markdown',"""Chín regression cũ được kiểm riêng; không ép vào holdout.
summary.json có thể báo NEEDS_PARSER_FIX khi các regression vắng mặt. Đọc
holdout_quality_audit.json và HTTP/raw để phân biệt thiếu dữ liệu với lỗi parser.
Không suy “hết lỗi” từ số cờ bằng 0 hoặc việc không tải được HTML.
""",'ask120-holdout-note'))
    nb['cells']=cells
    nb['metadata']['ask120_unified']={'schema':1,'default_mode':'replay',
        'modes':['replay','crawl_new','holdout_1000'],'holdout_payload_sha256':checksum}
    return nb


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',nargs='?',type=Path,help='Optional prepared/completed run to freeze as the new holdout')
    args=parser.parse_args()
    if args.run:
        bundle=freeze_run(args.run.resolve())
        SAMPLE_PATH.parent.mkdir(parents=True,exist_ok=True)
        SAMPLE_PATH.write_text(json.dumps(bundle,ensure_ascii=False),encoding='utf-8')
    from build_120ask_gate_notebook import main as build
    build()
    print('Unified notebook:',ROOT/'notebooks/check_120ask_50.ipynb')


if __name__=='__main__':main()
