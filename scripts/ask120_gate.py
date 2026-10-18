"""120ask replay and thread-level candidate admission. Never imports input-run code."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import random
import re
from urllib.parse import urlsplit
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

def _load_parser():
    path=Path(__file__).with_name('ask120_snapshot.py')
    if not path.exists(): path=Path(__file__).with_name('ask120.py')
    spec=importlib.util.spec_from_file_location('_gate_parser_'+str(path),path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

PARSER = _load_parser()
POLICY = {'version':'120ask-admission-v1','min_answer_chars':20,'manual_seed':20261020,
          'manual_include_minimum':50,'promotional_claims_require_review':True}
REGRESSIONS = ('1015858','3202910','3530545','3256774','3434509','378338','257785','13753474','77939582')
PROMO = re.compile(r'包治|根治|无(?:任何)?(?:的)?(?:毒)?副作用|没有(?:任何)?副作用|百分之百|100%\s*治愈|有特效|彻底治愈')
CORRUPT = re.compile(r'\ufffd|(?:Ã.|Â.){3,}|\?/[A-Za-z]+>')
GATE_VERSION = '120ask-gate-v1'


def sha(value):
    return hashlib.sha256(value if isinstance(value,bytes) else value.encode('utf-8')).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def policy_hash(policy):
    return sha(json.dumps(policy,sort_keys=True,ensure_ascii=False))


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)


def jsonl(path,rows):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8');tmp.replace(path)


def read_jsonl_bytes(body):
    return [json.loads(line) for line in body.decode('utf-8').splitlines() if line.strip()]


def canonical_question(url):
    p=urlsplit(url)
    if PARSER.is_question_url(url):
        return '120ask.com'+p.path
    raise ValueError('Not a canonical 120ask question URL: '+url)


class RunInput:
    def __init__(self,path):
        self.path=Path(path);self.zip=None;self.prefix=''
        if self.path.is_file():
            self.zip=zipfile.ZipFile(self.path)
            for name in self.zip.namelist(): self.safe_name(name.rstrip('/'))
            matches=[n for n in self.zip.namelist() if n=='manifest.json' or n.endswith('/manifest.json')]
            if len(matches)!=1: raise ValueError('Input ZIP requires exactly one run manifest')
            self.prefix=matches[0][:-len('manifest.json')]
    @staticmethod
    def safe_name(name):
        value=str(name).replace('\\','/')
        p=PurePosixPath(value)
        if not value or p.is_absolute() or '..' in p.parts or ':' in value:
            raise ValueError('Unsafe input path: '+value)
        return value
    def read(self,name):
        name=self.safe_name(name)
        if self.zip:
            info=self.zip.getinfo(self.prefix+name)
            if info.file_size>40*1024*1024: raise ValueError('Input member too large')
            return self.zip.read(info)
        path=(self.path/name).resolve()
        if not path.is_relative_to(self.path.resolve()): raise ValueError('Input path escapes run directory')
        return path.read_bytes()
    def exists(self,name):
        try:self.read(name);return True
        except (KeyError,FileNotFoundError):return False
    def close(self):
        if self.zip:self.zip.close()


def locate_input(zip_path=None,dir_path=None):
    if zip_path and dir_path: raise ValueError('Choose INPUT_RUN_ZIP or INPUT_RUN_DIR')
    if zip_path or dir_path:
        path=Path(zip_path or dir_path)
        if not path.exists(): raise FileNotFoundError(path)
        return path
    filename='check_120ask_20261018T022128241058Z.zip'
    matches=sorted(Path('/kaggle/input').rglob(filename)) if Path('/kaggle/input').exists() else []
    if not matches:
        local=Path('C:/Users/HP/Downloads')/filename
        if local.is_file():matches=[local]
    if len(matches)!=1:
        raise ValueError(f'Found {len(matches)} matching replay inputs; set INPUT_RUN_ZIP/INPUT_RUN_DIR explicitly.')
    return matches[0]


def parse_source_response(raw_bytes, metadata):
    doc=PARSER.extract(raw_bytes,metadata.get('final_url') or metadata['url'],metadata.get('content_type',''))
    return dict(metadata,**doc)


def source_flags(text):
    match=PROMO.search(text)
    return ([{'flag':'PROMOTIONAL_CLAIM_REVIEW','excerpt':text[max(0,match.start()-60):match.end()+100]}]
            if match else [])


def review_thread(thread,page,policy):
    main=[t for t in thread['turns'] if t['role']=='doctor_answer']
    parser_flags=list(thread.get('parser_flags',[]))
    warnings=[]
    if not page.get('question_asked_at'):warnings.append('QUESTION_DATE_MISSING')
    if not thread.get('doctor'):warnings.append('AUTHOR_METADATA_UNAVAILABLE')
    text='\n\n'.join(t['text'] for t in thread['turns'] if t['text'])
    flags=source_flags(text)
    reasons=[]
    decision='INCLUDE'
    if (page.get('replay_error') or page.get('access_status')!='VAO_DUOC'
            or type(page.get('id')) is not int or not page.get('raw_sha256')
            or not page.get('parser_sha256') or not page.get('policy_sha256')):
        decision='EXCLUDE';reasons.append('FETCH_OR_RAW_EVIDENCE_ERROR')
    elif not page.get('question_valid'):
        decision='EXCLUDE';reasons.append('QUESTION_MISSING_OR_AMBIGUOUS')
    elif not main or not any(t['text'] for t in main):
        decision='EXCLUDE';reasons.append('AUDIO_ONLY' if any(t['answer_type']=='audio' for t in main) else 'NO_TEXT_MAIN_ANSWER')
    elif CORRUPT.search(page.get('ask120_question','')+'\n'+text) or page.get('decode_warning'):
        decision='EXCLUDE';reasons.append('SEVERE_CORRUPTION')
    else:
        if any(len(PARSER.compact(re.sub(r'(?:病情分析|指导意见|医生询问)\s*[：:]','',t['text'])))<policy['min_answer_chars'] for t in main):
            reasons.append('SHORT_MAIN_ANSWER_REVIEW')
        if any(t['residual_markup'] for t in thread['turns']):
            reasons.append('RESIDUAL_MARKUP_REVIEW')
        if any(PARSER.AUDIO_FALLBACK.search(t['text']) for t in thread['turns']):
            reasons.append('AUDIO_FALLBACK_REVIEW')
        if thread.get('ownership_status')!='resolved':reasons.append('UNRESOLVED_OWNERSHIP')
        reasons.extend(parser_flags)
        if page['ask120_qc']['published_count_semantics']=='unresolved':
            reasons.append('PUBLISHED_COUNT_SEMANTICS_REVIEW')
        if any(m in text for m in PARSER.UI_MARKERS):reasons.append('UI_CONTAMINATION_REVIEW')
        if not page.get('title'):reasons.append('TITLE_MISSING_REVIEW')
        if page['ask120_qc'].get('unresolved_blocks'):reasons.append('UNRESOLVED_PAGE_FOLLOWUPS')
        if page.get('essential_media_missing'):reasons.append('ESSENTIAL_MEDIA_REVIEW')
        if any(t.get('attachment_urls') for t in thread['turns']):reasons.append('ESSENTIAL_ATTACHMENT_REVIEW')
        if flags and policy.get('promotional_claims_require_review'):reasons.append('SOURCE_CLAIM_REVIEW')
        if reasons:decision='REVIEW'
    return dict(thread,source_id=page['id'],url=page['url'],question=page.get('ask120_question',''),
        raw_sha256=page.get('raw_sha256'),raw_path=page.get('raw_path'),
        parser_sha256=page.get('parser_sha256'),policy_sha256=page.get('policy_sha256'),
        parser_version=PARSER.VERSION,corpus_decision=decision,decision_reasons=sorted(set(reasons)),
        parser_status='needs_review' if parser_flags else 'parsed',parser_flags=parser_flags,
        source_flags=flags,warnings=warnings)


def decide_page(threads,page):
    counts=Counter(t['corpus_decision'] for t in threads)
    if counts['INCLUDE']:
        decision='INCLUDE_PARTIAL' if counts['REVIEW'] or counts['EXCLUDE'] else 'INCLUDE'
    elif counts['REVIEW']:decision='REVIEW'
    else:decision='EXCLUDE'
    reasons=sorted({r for t in threads for r in t['decision_reasons']})
    if not threads:
        reasons=['RAW_EVIDENCE_ERROR' if page.get('replay_error') else
                 'QUESTION_MISSING_OR_AMBIGUOUS' if not page.get('question_valid') else 'NO_ANSWER_IN_FETCHED_HTML']
    return {'corpus_decision':decision,'decision_reasons':reasons,
            'include_thread_count':counts['INCLUDE'],'review_thread_count':counts['REVIEW'],
            'exclude_thread_count':counts['EXCLUDE']}


def build_candidate_document(page,included_threads):
    # Preserve the integer source ID; keep doctor and turn boundaries explicit.
    parts=[page.get('title',''),'问题：\n'+page['ask120_question']]
    spans=[]
    for thread in included_threads:
        for turn in thread['turns']:
            if not turn['text']:continue
            name=f"（{thread['doctor']}）" if thread.get('doctor') and turn['role']!='patient_followup' else ''
            chunk=f"{PARSER.LABELS[turn['role']]} {thread['index']}{name}：\n{turn['text']}"
            start=len('\n\n'.join(p for p in parts if p)) + 2
            parts.append(chunk)
            spans.append({'thread_id':thread['thread_id'],'reply_id':turn['reply_id'],
                          'turn_index':turn['turn_index'],'dom_locator':turn['dom_locator'],
                          'char_start':start,'char_end':start+len(chunk)})
    text='\n\n'.join(p for p in parts if p)
    return {'id':page['id'],'url':page['url'],'final_url':page.get('final_url') or page['url'],
        'title':page.get('title',''),'text':text,'domain':'www.120ask.com','extractor':PARSER.EXTRACTOR,
        'published_at':page.get('question_asked_at'),'raw_path':page['raw_path'],'raw_sha256':page['raw_sha256'],
        'text_sha256':sha(text),'duplicate_doc_ids':[],
        'parser_sha256':page['parser_sha256'],'policy_sha256':page['policy_sha256'],
        'included_thread_ids':[t['thread_id'] for t in included_threads],
        'excluded_or_review_threads':[{'thread_id':t['thread_id'],'decision':t['corpus_decision'],
            'reasons':t['decision_reasons']} for t in page['thread_decisions'] if t['corpus_decision']!='INCLUDE'],
        'source_spans':spans,'candidate_only':True}


def safe_raw(reader,record):
    body=reader.read(record['raw_path'])
    if record['raw_path'].endswith('.gz'):
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:body=stream.read(20*1024*1024+1)
    if len(body)>20*1024*1024:raise ValueError('Raw HTML exceeds replay limit')
    if not record.get('raw_sha256') or sha(body)!=record['raw_sha256']:raise ValueError('Raw hash mismatch')
    return body


def replay(input_path,out,policy=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    policy={**POLICY,**(policy or {})}
    reader=RunInput(input_path)
    p_hash=sha(Path(PARSER.__file__).read_bytes());g_hash=sha(Path(__file__).read_bytes());pol_hash=policy_hash(policy)
    parent=json.loads(reader.read('manifest.json'))
    samples=read_jsonl_bytes(reader.read('sample.jsonl'))
    if len({s['id'] for s in samples})!=len(samples):raise ValueError('Duplicate source IDs in sample')
    if any(type(s['id']) is not int for s in samples):raise ValueError('Source IDs must be original integers')
    identity={'mode':'replay','parent_run':str(Path(input_path).resolve()),'parent_manifest_sha256':sha(reader.read('manifest.json')),
        'parent_parser_sha256':(parent.get('snapshot_sha256') or {}).get('ask120_snapshot.py'),
        'parser_sha256':p_hash,'gate_sha256':g_hash,'policy_sha256':pol_hash,'policy':policy,
        'selected':len(samples),'sample_sha256':sha(reader.read('sample.jsonl'))}
    if Path(input_path).is_file():
        identity['parent_archive_sha256']=sha(Path(input_path).read_bytes())
    manifest_path=out/'manifest.json'
    if manifest_path.exists():
        previous=json.loads(manifest_path.read_text(encoding='utf-8'))
        if any(previous.get(k)!=v for k,v in identity.items()):raise ValueError('Replay identity changed; use a new output run')
    else:write_json(manifest_path,dict(identity,created_at=utc()))
    jsonl(out/'sample.jsonl',samples)
    old_results={r['id']:r for r in read_jsonl_bytes(reader.read('url_check.jsonl'))} if reader.exists('url_check.jsonl') else {}
    baseline=[]
    try:
        for i,sample in enumerate(samples,1):
            try:
                old=json.loads(reader.read(f"records/{sample['id']}.json"))
                if old['id']!=sample['id'] or old['url']!=sample['url']:raise ValueError('Source mapping differs from sample')
            except (KeyError,FileNotFoundError,ValueError) as exc:
                old=dict(sample,replay_error=f'Baseline record missing/invalid: {exc}')
            baseline.append(dict(old,baseline_probe=old_results.get(sample['id'],{})))
            output=out/'records'/f"{sample['id']}.json"
            if output.exists():
                saved=json.loads(output.read_text(encoding='utf-8'))
                if saved.get('parser_sha256')==p_hash and saved.get('policy_sha256')==pol_hash:
                    # Input directories can change without their manifest changing.
                    try:
                        safe_raw(reader,old)
                        continue
                    except (KeyError,FileNotFoundError,ValueError,OSError):
                        pass
                else:
                    raise ValueError('Checkpoint parser/policy mismatch; use a new output run')
            metadata={k:old.get(k) for k in ('id','url','final_url','content_type','http_status')}
            metadata.update(parser_sha256=p_hash,policy_sha256=pol_hash,
                baseline_quality_status=old.get('quality_status'),baseline_quality_flags=old.get('quality_flags',[]),
                baseline_probe_verdict=old_results.get(sample['id'],{}).get('verdict'),
                baseline_extractor=old.get('extractor'),baseline_main_answer_count=old.get('main_answer_count',0),
                baseline_card_count=len(old.get('ask120_threads',[])),baseline_text=old.get('text',''),
                raw_sha256=old.get('raw_sha256'),parent_raw_path=old.get('raw_path'))
            try:
                if old.get('replay_error'):raise ValueError(old['replay_error'])
                body=safe_raw(reader,old)
                path=Path('raw')/f"{sample['id']}_{sha(body)}.html.gz"
                (out/path).parent.mkdir(parents=True,exist_ok=True)
                (out/path).write_bytes(gzip.compress(body,mtime=0))
                metadata['raw_path']=path.as_posix()
                page=parse_source_response(body,metadata)
                page['access_status']='VAO_DUOC' if 200 <= (old.get('http_status') or 0) < 300 and not page['ask120_challenge_detected'] else 'KHONG_VAO_DUOC'
                page['essential_media_missing']='图片涉及用户隐私' in page['ask120_question_raw']
                page['parser_status']='needs_review' if page['ask120_review_reasons'] else 'parsed'
                threads=[review_thread(t,page,policy) for t in page['ask120_threads']]
                page.update(thread_decisions=threads,**decide_page(threads,page))
            except Exception as exc:
                page=dict(metadata,replay_error=f'{type(exc).__name__}: {exc}',access_status='RAW_ERROR',
                          parser_status='failed',parser_flags=['RAW_OR_PARSE_ERROR'],thread_decisions=[],
                          corpus_decision='EXCLUDE',decision_reasons=['RAW_EVIDENCE_ERROR'],
                          include_thread_count=0,review_thread_count=0,exclude_thread_count=0)
            write_json(output,page)
            if i%100==0:print(f"Replay {i}/{len(samples)}",flush=True)
    finally:
        reader.close()
        jsonl(out/'results_baseline.jsonl',baseline)
    return samples


def crawl_new(source,out,policy=None,*,limit=1000,seed=20261020,history_paths=(),support_dir=None,
              delay=2.,attempts=2,timeout=(8.,20.),budget=60.,trust_env=False,
              respect_robots=False,stop_on_block=True):
    """One worker, canonical-question reservoir sampling; immutable manifest on resume."""
    import math
    if type(limit) is not int or limit<1 or type(attempts) is not int or attempts<1:
        raise ValueError('limit/attempts must be positive integers')
    if not math.isfinite(delay) or delay<2:raise ValueError('crawl_new requires delay >= 2 seconds')
    if any(not math.isfinite(x) or x<=0 for x in (*timeout,budget)):raise ValueError('Invalid request bounds')
    policy={**POLICY,**(policy or {})};out=Path(out);out.mkdir(parents=True,exist_ok=True)
    p_hash=sha(Path(PARSER.__file__).read_bytes());pol_hash=policy_hash(policy)
    settings={'source':str(Path(source).resolve()),'limit':limit,'seed':seed,
        'history_paths':[str(p) for p in history_paths],'delay':delay,'attempts':attempts,
        'timeout':list(timeout),'budget':budget,'trust_env':trust_env,
        'respect_robots':respect_robots,'stop_on_block':stop_on_block}
    identity={'mode':'crawl_new','parser_sha256':p_hash,'policy_sha256':pol_hash,
              'gate_sha256':sha(Path(__file__).read_bytes()),'policy':policy,'settings':settings}
    if (out/'manifest.json').exists():
        saved=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
        if any(saved.get(k)!=v for k,v in identity.items()):raise ValueError('Crawl identity changed; use a new output run')
        if sha((out/'sample.jsonl').read_bytes())!=saved['sample_sha256']:raise ValueError('Sample manifest changed')
        samples=read_jsonl_bytes((out/'sample.jsonl').read_bytes())
    else:
        seen_history=set();history_files=[]
        for value in history_paths:
            path=Path(value)
            if not path.exists():raise FileNotFoundError(path)
            if path.suffix.lower()=='.zip':
                reader=RunInput(path)
                try:
                    rows=read_jsonl_bytes(reader.read('sample.jsonl'))
                    history_files.append({'path':str(path),'sha256':sha(reader.read('sample.jsonl'))})
                finally:reader.close()
            else:
                files=[path] if path.is_file() else sorted(path.rglob('sample.jsonl'))
                if not files:raise ValueError('History directory has no sample.jsonl')
                rows=[]
                for file in files:
                    content=file.read_bytes();rows.extend(read_jsonl_bytes(content))
                    history_files.append({'path':str(file),'sha256':sha(content)})
            for row in rows:
                url=row.get('source_url') or row.get('url')
                if url and PARSER.is_question_url(url):seen_history.add(canonical_question(url))
        table=pq.ParquetFile(source)
        if not {'id','url'}<=set(table.schema_arrow.names):raise ValueError('Source must contain id,url')
        if table.schema_arrow.field('id').type!=pa.int64():raise ValueError('Source id must be int64')
        population={};id_urls={}
        for batch in table.iter_batches(columns=['id','url']):
            for row in batch.to_pylist():
                if not row.get('url') or not PARSER.is_question_url(row['url']):continue
                if type(row['id']) is not int:raise ValueError('Source ID missing')
                key=canonical_question(row['url'])
                if row['id'] in id_urls and id_urls[row['id']]!=key:
                    raise ValueError('One source ID maps to multiple question URLs')
                id_urls[row['id']]=key
                population.setdefault(key,[]).append(row)
        rng=random.Random(seed);samples=[];eligible=excluded=0
        for key,aliases in population.items():
            if key in seen_history:excluded+=1;continue
            eligible+=1
            row=dict(aliases[0],canonical_question=key,domain='www.120ask.com',
                     source_aliases=aliases,source_alias_ids=sorted({r['id'] for r in aliases}))
            if len(samples)<limit:samples.append(row)
            else:
                position=rng.randrange(eligible)
                if position<limit:samples[position]=row
        if len(samples)<limit:raise ValueError(f'Only {len(samples)} eligible questions; requested {limit}')
        rng.shuffle(samples)
        jsonl(out/'sample.jsonl',samples)
        write_json(out/'manifest.json',dict(identity,created_at=utc(),sample_sha256=sha((out/'sample.jsonl').read_bytes()),
            source_sha256=sha(Path(source).read_bytes()),history_files=history_files,
            history_unique_questions=len(seen_history),excluded_history=excluded,
            history_scope='provided_history_only' if history_files else 'no_history_provided',
            unseen_in_all_previous_runs_guaranteed=False,selected=len(samples)))
    support=Path(support_dir or out/'support')
    modules=[]
    for name in ('crawler_snapshot.py','priority_probe_snapshot.py'):
        path=support/name;spec=importlib.util.spec_from_file_location('_gate_new_'+name[:-3],path)
        module=importlib.util.module_from_spec(spec)
        import sys
        sys.modules[spec.name]=module;spec.loader.exec_module(module);modules.append(module)
    crawler,probe=modules;crawler.TRUST_ENV=trust_env
    fetcher=crawler.Fetcher(out,delay=delay,attempts=attempts);fetcher.stop_on_rate_limit=stop_on_block
    baseline=[]
    try:
        for i,sample in enumerate(samples,1):
            path=out/'records'/f"{sample['id']}.json"
            if path.exists():
                saved=json.loads(path.read_text(encoding='utf-8'))
                if saved.get('parser_sha256')!=p_hash or saved.get('policy_sha256')!=pol_hash:
                    raise ValueError('Checkpoint parser/policy mismatch')
                continue
            old=probe.request_record(crawler,fetcher,sample,out,'ViBioMIR-120askGate/1.0',
                timeout,budget,respect_robots=respect_robots,record_dir='fetch_records')
            baseline.append(old)
            metadata={k:old.get(k) for k in ('id','url','final_url','content_type','http_status','raw_path','raw_sha256')}
            metadata.update(parser_sha256=p_hash,policy_sha256=pol_hash,
                baseline_quality_status=old.get('quality_status'),baseline_quality_flags=old.get('quality_flags',[]),
                baseline_probe_verdict=probe.access_outcome(old)[0],baseline_text=old.get('text',''),
                baseline_origin='fetch_stage_current_parser',source_aliases=sample.get('source_aliases',[]))
            try:
                if not old.get('raw_path'):raise ValueError('Fetch returned no raw HTML')
                reader=RunInput(out)
                body=safe_raw(reader,old)
                page=parse_source_response(body,metadata)
                page['access_status']=probe.access_outcome(old)[0]
                page['essential_media_missing']='图片涉及用户隐私' in page['ask120_question_raw']
                page['parser_status']='needs_review' if page['ask120_review_reasons'] else 'parsed'
                threads=[review_thread(t,page,policy) for t in page['ask120_threads']]
                page.update(thread_decisions=threads,**decide_page(threads,page))
            except Exception as exc:
                page=dict(metadata,replay_error=f'{type(exc).__name__}: {exc}',access_status='RAW_ERROR',
                    parser_status='failed',thread_decisions=[],corpus_decision='EXCLUDE',
                    decision_reasons=['FETCH_OR_RAW_EVIDENCE_ERROR'],include_thread_count=0,
                    review_thread_count=0,exclude_thread_count=0)
            write_json(path,page)
            if i%25==0:print(f'Crawl {i}/{len(samples)}',flush=True)
            if stop_on_block and (old.get('http_status')==429 or old.get('challenge_detected')
                                  or old.get('ask120_challenge_detected')):
                break
    finally:
        fetcher.session().close()
        # Keep all baseline checkpoints across invocation/resume.
        baseline=[json.loads(p.read_text(encoding='utf-8')) for p in sorted((out/'fetch_records').glob('*.json'))]
        jsonl(out/'results_baseline.jsonl',baseline)
    return samples


PRODUCTION_FIELDS=('id','url','final_url','title','text','domain','extractor','published_at',
                   'raw_path','raw_sha256','text_sha256','duplicate_doc_ids')
CANDIDATE_SCHEMA=pa.schema([('id',pa.int64())]+[(k,pa.list_(pa.int64()) if k=='duplicate_doc_ids' else pa.string())
    for k in PRODUCTION_FIELDS if k!='id'])


def save_csv(path,rows,fields):
    with Path(path).open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(row.get(k),ensure_ascii=False) if isinstance(row.get(k),(dict,list)) else row.get(k)
                             for k in fields})


def load_manual(path,pages):
    if not path:return {}
    path=Path(path)
    if path.suffix=='.csv':
        with path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    else:rows=read_jsonl_bytes(path.read_bytes())
    result={}
    for row in rows:
        key=(int(row['source_id']),row['thread_id'])
        if key in result:raise ValueError('Duplicate manual review row')
        if row.get('reviewer_decision'):
            if row['reviewer_decision'] not in ('INCLUDE','REVIEW','EXCLUDE'):raise ValueError('Invalid manual decision')
            if not row.get('reviewed_at') or not row.get('reviewer_notes'):raise ValueError('Manual review requires time and notes')
            page=pages.get(key[0])
            if not page or row.get('raw_sha256')!=page.get('raw_sha256') or row.get('parser_sha256')!=page.get('parser_sha256') or row.get('policy_sha256')!=page.get('policy_sha256'):
                raise ValueError('Stale manual review provenance')
        result[key]=row
    return result


def build_outputs(out, *, manual_review_path=None, export_candidates=True):
    out=Path(out)
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'));policy=manifest['policy']
    samples=read_jsonl_bytes((out/'sample.jsonl').read_bytes())
    pages={s['id']:json.loads((out/'records'/f"{s['id']}.json").read_text(encoding='utf-8'))
           for s in samples if (out/'records'/f"{s['id']}.json").exists()}
    manual=load_manual(manual_review_path,pages)
    all_threads=[]
    # Decisions are recomputed from immutable parsed checkpoints on every aggregation.
    for page in pages.values():
        for t in page.get('thread_decisions',[]):
            label=manual.get((page['id'],t['thread_id']),{})
            if label.get('reviewer_decision'):
                t['manual_review']=label
                # A human may resolve review flags, never bypass hard missing/raw/audio blockers.
                structural={'UNRESOLVED_OWNERSHIP','UNKNOWN_FOLLOWUP_ROLE','UNRESOLVED_PAGE_FOLLOWUPS',
                            'RESIDUAL_MARKUP_REVIEW','AUDIO_FALLBACK_REVIEW'}
                if label['reviewer_decision']=='INCLUDE' and structural.intersection(t['decision_reasons']):
                    t['manual_override_blocked']='Structural issues need parser/ownership correction first'
                elif t['corpus_decision']!='EXCLUDE' or label['reviewer_decision']!='INCLUDE':
                    t['corpus_decision']=label['reviewer_decision']
            all_threads.append(t)
        page.update(decide_page(page.get('thread_decisions',[]),page))
    candidates=[]
    violations=[]
    for page in pages.values():
        included=[t for t in page.get('thread_decisions',[]) if t['corpus_decision']=='INCLUDE']
        if not included:continue
        doc=build_candidate_document(page,included)
        if (PARSER.AUDIO_FALLBACK.search(doc['text']) or PARSER.LEGACY_MARKUP.search(doc['text'])
                or CORRUPT.search(doc['text']) or not page.get('question_valid')
                or not doc.get('raw_sha256') or type(doc['id']) is not int
                or any(t.get('ownership_status')!='resolved' for t in included)):
            violations.append(page['id']);continue
        candidates.append(doc)
    # One source ID per candidate. Cross-ID same URL is reported, never silently remapped.
    aliases=defaultdict(list)
    for sample in samples:
        try:aliases[canonical_question(sample['url'])].append(sample['id'])
        except ValueError:pass
    aliases={k:v for k,v in aliases.items() if len(v)>1}
    jsonl(out/'results_reparsed.jsonl',list(pages.values()))
    jsonl(out/'qa_threads_all.jsonl',all_threads)
    for label in ('INCLUDE','REVIEW','EXCLUDE'):
        jsonl(out/f'qa_threads_{label.lower()}.jsonl',[t for t in all_threads if t['corpus_decision']==label])
    # Legacy diagnostics name stays all-thread, never a silently filtered corpus.
    jsonl(out/'qa_threads.jsonl',all_threads)
    jsonl(out/'corpus_candidates.jsonl',candidates if export_candidates else [])
    compact_rows=[{k:d.get(k) for k in PRODUCTION_FIELDS} for d in candidates] if export_candidates else []
    pq.write_table(pa.Table.from_pylist(compact_rows,schema=CANDIDATE_SCHEMA),out/'corpus_candidates.parquet')
    decisions=[{'id':p['id'],'url':p['url'],'access_status':p['access_status'],
        'parser_status':p['parser_status'],**{k:p[k] for k in ('corpus_decision','decision_reasons',
            'include_thread_count','review_thread_count','exclude_thread_count')},
        'baseline_quality_status':p.get('baseline_quality_status'),'baseline_probe_verdict':p.get('baseline_probe_verdict')}
        for p in pages.values()]
    save_csv(out/'corpus_decisions.csv',decisions,['id','url','access_status','parser_status','corpus_decision',
        'decision_reasons','include_thread_count','review_thread_count','exclude_thread_count',
        'baseline_quality_status','baseline_probe_verdict'])
    # Seeded, stratified review: cycle through date decade / length / partial-page bins.
    bins=defaultdict(list)
    for t in all_threads:
        p=pages[t['source_id']]
        length=sum(len(x['text']) for x in t['turns'])
        date=p.get('question_asked_at') or 'unknown'
        template=t['turns'][0]['dom_locator'].rsplit('/',1)[-1].split('[')[0]
        key=(t['corpus_decision'],date[:3],template, 'short' if length<200 else 'medium' if length<1000 else 'long',
             p['corpus_decision']=='INCLUDE_PARTIAL')
        bins[key].append(t)
    rng=random.Random(policy['manual_seed'])
    for key in sorted(bins):rng.shuffle(bins[key])
    include_sample=[]
    while len(include_sample)<min(policy['manual_include_minimum'],sum(t['corpus_decision']=='INCLUDE' for t in all_threads)):
        for key in sorted(bins):
            if key[0]=='INCLUDE' and bins[key] and len(include_sample)<policy['manual_include_minimum']:
                include_sample.append(bins[key].pop())
    required={(t['source_id'],t['thread_id']) for t in include_sample}
    for t in all_threads:
        p=pages[t['source_id']]
        qid=urlsplit(t['url']).path.split('/')[-1].split('.')[0]
        if qid in REGRESSIONS or t['source_flags'] or t.get('parser_flags'):
            required.add((t['source_id'],t['thread_id']))
    # Every newly observed decision-reason group gets a review representative.
    for reason in sorted({r for t in all_threads for r in t['decision_reasons']}):
        t=next(t for t in all_threads if reason in t['decision_reasons'])
        required.add((t['source_id'],t['thread_id']))
    review_rows=[]
    for t in all_threads:
        key=(t['source_id'],t['thread_id'])
        if key not in required:continue
        label=manual.get(key,{})
        review_rows.append({'source_id':key[0],'thread_id':key[1],'url':t['url'],
            'corpus_decision':t['corpus_decision'],'decision_reasons':t['decision_reasons'],
            'raw_path':t['raw_path'],'raw_sha256':t['raw_sha256'],'parser_sha256':t['parser_sha256'],
            'policy_sha256':t['policy_sha256'],'review_status':'REVIEWED' if label.get('reviewer_decision') else 'MANUAL_REVIEW_PENDING',
            'reviewer_decision':label.get('reviewer_decision',''),'reviewer_notes':label.get('reviewer_notes',''),
            'reviewed_at':label.get('reviewed_at','')})
    for page in pages.values():
        qid=urlsplit(page['url']).path.split('/')[-1].split('.')[0]
        if not page.get('thread_decisions') and (qid in REGRESSIONS or page.get('replay_error')):
            label=manual.get((page['id'],'__page__'),{})
            review_rows.append({'source_id':page['id'],'thread_id':'__page__','url':page['url'],
                'corpus_decision':page['corpus_decision'],'decision_reasons':page['decision_reasons'],
                'raw_path':page.get('raw_path'),'raw_sha256':page.get('raw_sha256'),
                'parser_sha256':page['parser_sha256'],'policy_sha256':page['policy_sha256'],
                'review_status':'REVIEWED' if label.get('reviewer_decision') else 'MANUAL_REVIEW_PENDING',
                'reviewer_decision':label.get('reviewer_decision',''),'reviewer_notes':label.get('reviewer_notes',''),
                'reviewed_at':label.get('reviewed_at','')})
    save_csv(out/'manual_review_sheet.csv',review_rows,['source_id','thread_id','url','corpus_decision','decision_reasons',
        'raw_path','raw_sha256','parser_sha256','policy_sha256','review_status','reviewer_decision','reviewer_notes','reviewed_at'])
    comparison=[]
    for p in pages.values():
        qid=urlsplit(p['url']).path.split('/')[-1].split('.')[0]
        if qid not in REGRESSIONS and 'ask120_published_reply_mismatch' not in p.get('baseline_quality_flags',[]):continue
        qc=p.get('ask120_qc',{})
        comparison.append({'question_id':qid,'id':p['id'],'url':p['url'],'baseline_text':p.get('baseline_text',''),
            'new_text':p.get('text',''),'baseline_main_answers':p.get('baseline_main_answer_count'),
            'card_count':qc.get('source_card_count'),'reply_count':qc.get('source_reply_count'),
            'text_answers':p.get('usable_text_main_answers'),'audio_answers':p.get('audio_main_answers'),
            'published_count':qc.get('published_reply_count'),'count_semantics':qc.get('published_count_semantics'),
            'decision':p['corpus_decision'],'reasons':p['decision_reasons']})
    save_csv(out/'regression_comparison.csv',comparison,['question_id','id','url','baseline_text','new_text',
        'baseline_main_answers','card_count','reply_count','text_answers','audio_answers','published_count',
        'count_semantics','decision','reasons'])
    missing_regressions=sorted(set(REGRESSIONS)-{r['question_id'] for r in comparison})
    regression_checks=validate_regressions(pages)
    reviewed=sum(bool(r['reviewer_decision']) for r in review_rows)
    critical_manual=any('PARSER_ERROR' in r.get('reviewer_notes','').upper() for r in review_rows)
    # Any rejected final invariant blocks site readiness even though that document is not exported.
    readiness=('NEEDS_PARSER_FIX' if len(pages)!=len(samples) or violations or any(p.get('replay_error') for p in pages.values()) or critical_manual or missing_regressions
               or any(not r['passed'] for r in regression_checks.values())
               else 'READY_FOR_FILTERED_CORPUS' if review_rows and reviewed==len(review_rows) and len(include_sample)>=50
               else 'READY_FOR_FILTERED_PILOT' if candidates else 'NEEDS_PARSER_FIX')
    matrix=Counter((p.get('baseline_probe_verdict') or 'UNKNOWN',p['corpus_decision']) for p in pages.values())
    summary={'mode':manifest['mode'],'selected':len(samples),'reparsed':len(pages),'pending':len(samples)-len(pages),
        'raw_verified':sum(not p.get('replay_error') for p in pages.values()),
        'raw_or_parse_errors':sum(bool(p.get('replay_error')) for p in pages.values()),
        'parser_version':PARSER.VERSION,'parser_sha256':manifest['parser_sha256'],'policy_sha256':manifest['policy_sha256'],
        'baseline_production_accepted':sum(p.get('baseline_quality_status')=='accepted' for p in pages.values()),
        'page_decisions':dict(Counter(p['corpus_decision'] for p in pages.values())),
        'thread_decisions':dict(Counter(t['corpus_decision'] for t in all_threads)),
        'candidate_documents':len(candidates),'candidate_unique_source_ids':len({d['id'] for d in candidates}),
        'candidate_threads':sum(len(d['included_thread_ids']) for d in candidates),
        'export_candidate_corpus':export_candidates,'aliases_same_question':aliases,
        'baseline_to_new':[{'baseline':a,'new':b,'pages':n} for (a,b),n in sorted(matrix.items())],
        'units':{k:sum(p.get(k,0) for p in pages.values()) for k in ('source_card_count','source_reply_blocks',
            'source_reply_count','text_main_answers','audio_main_answers','mixed_main_answers','usable_text_main_answers',
            'followup_count','patient_followups','doctor_followups')},
        'thread_decision_reasons':dict(Counter(r for t in all_threads for r in set(t['decision_reasons']))),
        'source_flags':dict(Counter(f['flag'] for t in all_threads for f in t['source_flags'])),
        'source_flag_pages':len({t['source_id'] for t in all_threads if t['source_flags']}),
        'question_dates_by_decade':dict(Counter((p.get('question_asked_at') or 'unknown')[:3] for p in pages.values())),
        'reply_dom_templates':dict(Counter(t['turns'][0]['dom_locator'].rsplit('/',1)[-1].split('[')[0] for t in all_threads)),
        'pages_with_audio':sum(bool(p.get('audio_main_answers') or p.get('mixed_main_answers')) for p in pages.values()),
        'no_answer_in_fetched_html':sum(not p.get('source_reply_blocks') and not p.get('replay_error') for p in pages.values()),
        'duplicate_groups_by_role':dict(Counter(g['kind'] for p in pages.values() for g in p.get('ask120_qc',{}).get('duplicates_by_role',[]))),
        'candidate_audio_fallbacks':sum(bool(PARSER.AUDIO_FALLBACK.search(d['text'])) for d in candidates),
        'candidate_legacy_markup':sum(bool(PARSER.LEGACY_MARKUP.search(d['text'])) for d in candidates),
        'candidate_invariant_violations':violations,'missing_regressions':missing_regressions,
        'regression_checks':regression_checks,
        'manual_include_sample':len(include_sample),'manual_required':len(review_rows),'manual_reviewed':reviewed,
        'readiness':readiness,'medical_accuracy_reviewed':False}
    write_json(out/'summary.json',summary)
    lines=['# 120ask — parser và xét nhập candidate corpus','',
        'INCLUDE chỉ là đủ điều kiện trích xuất theo policy, không xác nhận y khoa hoặc tự publish.',
        'Thiếu nhãn review thủ công vẫn là MANUAL_REVIEW_PENDING.','',
        json.dumps(summary,ensure_ascii=False,indent=2),'','## Regression trước/sau']
    for row in comparison:
        lines += [f"### {row['question_id']}: {row['decision']}",row['url'],
            f"cards={row['card_count']}, replies={row['reply_count']}, published={row['published_count']}, semantics={row['count_semantics']}",
            'Trước:\n'+row['baseline_text'][:1200],'Sau:\n'+row['new_text'][:1200]]
    lines += ['','## Mẫu đa dạng theo quyết định']
    for decision in ('INCLUDE','REVIEW','EXCLUDE','INCLUDE_PARTIAL'):
        subset=[p for p in pages.values() if p['corpus_decision']==decision]
        random.Random(policy['manual_seed']).shuffle(subset)
        for p in subset[:3]:
            lines += [f"### {decision}: {p['id']}",p['url'],str(p['decision_reasons']),p.get('text','')[:1000]]
    lines += ['','Kết luận: '+readiness,
        'Chỉ mở rộng nhóm được lọc theo policy; cần đối chiếu raw và hoàn tất phiếu review trước khi gọi là corpus có lọc đã duyệt.',
        'Ngày lưu là ngày hỏi, không suy thành ngày bác sĩ trả lời. Không crawl toàn domain, không upload.']
    (out/'report.md').write_text('\n\n'.join(lines),encoding='utf-8')
    return summary


def validate_regressions(pages):
    by_qid={urlsplit(p['url']).path.split('/')[-1].split('.')[0]:p for p in pages.values()}
    results={}
    for qid in REGRESSIONS:
        p=by_qid.get(qid)
        if not p:
            results[qid]={'passed':False,'reason':'Not present in supplied input'};continue
        turns=[turn for t in p.get('ask120_threads',[]) for turn in t['turns']]
        mains=[t for t in turns if t['role']=='doctor_answer']
        qc=p.get('ask120_qc',{})
        passed=not p.get('replay_error')
        if qid=='1015858':
            passed=passed and p.get('usable_text_main_answers')==0 and len(mains)==2 and all(
                t['answer_type']=='audio' and not t['text'] and t['media_urls'] for t in mains)
        elif qid=='3202910':
            ids={t.get('reply_id') for t in mains}
            passed=passed and {'reply500933','reply505382'}<=ids and qc.get('published_count_semantics')=='card_count_matches_template'
            passed=passed and any(t.get('source_flags') for t in p.get('thread_decisions',[]))
        elif qid in ('3530545','3256774','3434509'):
            passed=passed and not PARSER.LEGACY_MARKUP.search(p.get('text','')) and any(
                t['normalization_actions'] for t in turns) and all(t['dom_locator'] for t in turns)
            if qid=='3256774':passed=passed and len(p.get('ask120_threads',[]))==2
            if qid=='3434509':passed=passed and '\n' in mains[0]['text']
        elif qid=='378338':passed=passed and not p.get('question_valid') and p['corpus_decision']=='EXCLUDE'
        elif qid=='257785':passed=passed and p.get('question_valid') and qc.get('source_reply_blocks')==0
        elif qid=='13753474':
            passed=passed and p.get('followup_count')==13 and not qc.get('unresolved_blocks')
            passed=passed and not any(g['kind']=='duplicate_main_answer' for g in qc.get('duplicates_by_role',[]))
        elif qid=='77939582':
            passed=passed and p.get('followup_count')==10 and any(
                g['kind']=='repeated_patient_followup' for g in qc.get('duplicates_by_role',[]))
        results[qid]={'passed':bool(passed),'source_id':p['id']}
    return results
