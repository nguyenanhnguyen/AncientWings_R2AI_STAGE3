"""Bounded, sequential access measurements using the production Long Chau client."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import time
import uuid
import zipfile

VERSION = 'longchau-rate-check-v1'
DEFAULT_STAGES = [{'delay_seconds':10.,'urls':20}, {'delay_seconds':7.5,'urls':20},
                  {'delay_seconds':5.,'urls':20}]


def validate_stages(stages):
    if not isinstance(stages,list) or not 1 <= len(stages) <= 6:
        raise ValueError('Use 1..6 rate-check stages.')
    result=[]
    for stage in stages:
        delay,count=stage['delay_seconds'],stage['urls']
        if not isinstance(delay,(int,float)) or not math.isfinite(delay) or not 5 <= delay <= 60:
            raise ValueError('Rate-check delay must be 5..60 seconds.')
        if type(count) is not int or count < 1: raise ValueError('Stage URL count must be positive.')
        result.append({'delay_seconds':float(delay),'urls':count})
    if sum(s['urls'] for s in result)>500: raise ValueError('Rate check is bounded to 500 unique URLs.')
    if any(a['delay_seconds']<b['delay_seconds'] for a,b in zip(result,result[1:])):
        raise ValueError('Start with slower stages, then move toward the configured crawl rate.')
    return result


def rate_headers(headers):
    return {k.lower():str(v)[:500] for k,v in headers.items()
            if k.lower() in ('retry-after','server','cf-ray','cf-mitigated','cf-cache-status')
            or k.lower().startswith(('ratelimit','x-ratelimit','x-rate-limit'))}


def gate_value(crawler,path):
    if not path.exists(): return 0.
    value=crawler.load_json(path).get('not_before',0.)
    if not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
        raise ValueError('Invalid cooldown gate: '+str(path))
    return float(value)


def accessible(record):
    unverified={'longchau_identity_mismatch','longchau_missing_current_json','longchau_invalid_current_json',
                'longchau_missing_article_body','longchau_article_boundary_ambiguous'}
    return (record.get('status')=='extracted' and 200 <= (record.get('http_status') or 0) < 300
            and not record.get('challenge_detected') and not unverified.intersection(record.get('longchau_review_reasons') or []))


def measure(crawler,probe,longchau,samples,out,**options):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    with crawler.run_lock(out):
        return _measure(crawler,probe,longchau,samples,out,**options)


def _measure(crawler,probe,longchau,samples,out,*,stages=None,cooldown_dirs=(),share_cooldown_dir=None,
            max_seconds=1200.,respect_robots=False,environment=None):
    stages=validate_stages(DEFAULT_STAGES if stages is None else stages)
    if not isinstance(max_seconds,(int,float)) or not math.isfinite(max_seconds) or max_seconds<1:
        raise ValueError('max_seconds must be positive and finite.')
    selected=samples[:sum(s['urls'] for s in stages)]
    if not selected or len({s['id'] for s in selected})!=len(selected) or len({s['url'] for s in selected})!=len(selected):
        raise ValueError('Rate-check samples must have unique IDs and URLs.')
    if any(type(s['id']) is not int or s['id']<0 for s in selected): raise ValueError('Source IDs must be nonnegative integers.')
    if any(not longchau.is_host(s['url']) for s in selected): raise ValueError('Only Long Chau URLs are supported.')
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    identity={'version':VERSION,'stages':stages,'samples':selected,'respect_robots':respect_robots,
        'max_seconds':max_seconds,'client_sha256':crawler.file_hash(longchau.__file__),
        'core_sha256':crawler.file_hash(crawler.__file__),'probe_sha256':crawler.file_hash(probe.__file__),
        'rate_checker_sha256':crawler.file_hash(__file__)}
    config_path=out/'rate_check_config.json'
    if not config_path.exists() and any(p.name not in ('_runtime','longchau_request_gate.json','.crawl.lock') for p in out.iterdir()):
        raise ValueError('Use a separate fresh directory for the rate check, not an existing crawl run.')
    if config_path.exists() and crawler.load_json(config_path)!=identity:
        raise ValueError('Probe selection/code/settings changed; choose a new RATE_CHECK_RUN_TAG.')
    crawler.write_json(config_path,identity)
    crawler.atomic_bytes(out/'rate_check_snapshot.py',Path(__file__).read_bytes())
    gate=out/'longchau_request_gate.json'
    shared_gates=[Path(p)/'longchau_request_gate.json' for p in cooldown_dirs if p]
    destination_gate=Path(share_cooldown_dir)/'longchau_request_gate.json' if share_cooldown_dir else None
    if destination_gate is not None:shared_gates.append(destination_gate)
    paths=[gate]+shared_gates
    not_before=max(gate_value(crawler,p) for p in paths)
    if not_before: crawler.write_json(gate,{'not_before':not_before})
    assignments={};offset=0
    for stage_index,stage in enumerate(stages):
        for sample in selected[offset:offset+stage['urls']]: assignments[sample['id']]=stage_index
        offset+=stage['urls']
    records={}
    for sample in selected:
        path=out/'probe_records'/f"{sample['id']}.json"
        if not path.exists():continue
        record=crawler.load_json(path)
        if (record.get('id'),record.get('url'))!=(sample['id'],sample['url']):
            raise ValueError('Rate-check record ID/URL mismatch.')
        if record.get('status')=='extracted':
            raw_path=(out/record['raw_path']).resolve()
            if not raw_path.is_relative_to((out/'raw').resolve()):raise ValueError('Probe raw path escapes run.')
            with gzip.open(raw_path,'rb') as f:body=f.read(10*1024*1024+1)
            if len(body)>10*1024*1024:raise ValueError('Probe raw exceeds body size limit.')
            if crawler.digest(body)!=record['raw_sha256'] or crawler.digest(record['text'].encode())!=record['text_sha256']:
                raise ValueError('Rate-check raw/text hash mismatch.')
        records[sample['id']]=record
    pending=[s for s in selected if not accessible(records.get(s['id'],{}))]
    run_id=uuid.uuid4().hex
    events=[];stop='completed';fetcher=None
    started=time.monotonic()
    current={'stage':0,'id':None,'url':None}

    def observe(original):
        def request(*args,**kwargs):
            event={'invocation_id':run_id,'sequence':len(events)+1,'stage':current['stage'],
                'id':current['id'],'url':args[0],'started_at':crawler.utc(),'http_status':None}
            try:
                status,headers,body=original(*args,**kwargs)
                lower=body[:16384].lower()
                event.update(http_status=status,headers=rate_headers(headers),
                    cloudflare_1015=b'cloudflare' in lower and b'you are being rate limited' in lower,
                    challenge=probe.challenge_page(headers,body))
                return status,headers,body
            except BaseException as exc:
                event['exception_class']=type(exc).__name__
                raise
            finally:
                event.update(finished_at=crawler.utc(),finished_epoch=time.time())
                events.append(event)
                with (out/'rate_check_requests.jsonl').open('a',encoding='utf-8') as f:
                    f.write(json.dumps(event,ensure_ascii=False)+'\n')
        return request

    try:
        if pending and not_before-time.time()>max(s['delay_seconds'] for s in stages):
            stop='deferred_cooldown'
        elif pending:
            config=longchau.validate_config({'delay':stages[0]['delay_seconds'],'attempts':1,
                'timeout':[10.,30.],'budget':90.})
            fetcher=longchau.make_fetcher(crawler,out,config)
            fetcher.request_once=observe(fetcher.request_once)
            for sample in pending:
                remaining=max_seconds-(time.monotonic()-started)
                if remaining<1:stop='time_budget';break
                if gate_value(crawler,gate)-time.time()>max(s['delay_seconds'] for s in stages):
                    stop='deferred_cooldown';break
                stage_index=assignments[sample['id']]
                fetcher.delay=stages[stage_index]['delay_seconds']
                current.update(stage=stage_index,id=sample['id'],url=sample['url'])
                path=out/'probe_records'/f"{sample['id']}.json"
                if path.exists():
                    old=path.read_bytes();crawler.atomic_bytes(out/'previous_records'/f"{sample['id']}_{crawler.digest(old)}.json",old)
                event_start=len(events)
                record=probe.request_record(crawler,fetcher,sample,out,crawler.UA,
                    config['timeout'],min(config['budget'],remaining),respect_robots=respect_robots,record_dir='probe_records')
                record.update(engine='curl_cffi',rate_check_stage=stage_index)
                crawler.write_json(path,record)
                records[sample['id']]=record
                recent=events[event_start:]
                if any(e.get('http_status')==429 or e.get('cloudflare_1015') for e in recent):stop='rate_limited'
                elif any(e.get('challenge') or e.get('http_status')==403 for e in recent):stop='blocked_or_challenge'
                elif record.get('status')!='extracted':stop='request_error'
                elif not accessible(record):stop='unverified_page'
                print(json.dumps({'event':'rate_check_progress','stage':stage_index+1,
                    'delay_seconds':fetcher.delay,'completed':len(records),'selected':len(selected),
                    'id':sample['id'],'http_status':record.get('http_status'),'status':stop},ensure_ascii=False),flush=True)
                if stop!='completed':break
    except BaseException:
        stop='interrupted';raise
    finally:
        if fetcher:fetcher.close()
        not_before=gate_value(crawler,gate)
        # Share observed cooldown with the following normal crawl; do not reset any gate.
        if not_before>time.time() and destination_gate is not None:
            crawler.write_json(destination_gate,{'not_before':max(not_before,gate_value(crawler,destination_gate))})
        stage_reports=[]
        for i,stage in enumerate(stages):
            group=[r for id_,r in records.items() if assignments[id_]==i]
            reqs=[e for e in events if e['stage']==i]
            span=reqs[-1]['finished_epoch']-reqs[0]['finished_epoch'] if len(reqs)>1 else 0
            stage_reports.append(dict(stage,stage=i+1,selected=sum(j==i for j in assignments.values()),
                attempted_urls=len(group),http_statuses=dict(Counter(str(r.get('http_status')) for r in group)),
                observed_http_requests_this_invocation=len(reqs),
                observed_requests_per_minute=round(60*(len(reqs)-1)/span,3) if span>0 else None))
        advertised=[e['headers'] for e in events if any(k.startswith(('ratelimit','x-ratelimit','x-rate-limit')) for k in e.get('headers',{}))]
        summary={'kind':'rate_check_only','version':VERSION,'status':stop,'created_at':crawler.utc(),
            'environment':environment or platform.system(),'engine':'curl_cffi','workers':1,
            'selected':len(selected),'attempted_urls':len(records),'accessible':sum(accessible(r) for r in records.values()),
            'http_statuses':dict(Counter(str(r.get('http_status')) for r in records.values())),
            'http_attempts_this_invocation':len(events),'elapsed_seconds':round(time.monotonic()-started,3),
            'cooldown_not_before_utc':datetime.fromtimestamp(not_before,timezone.utc).isoformat() if not_before>time.time() else None,
            'server_advertised_rate_headers':advertised,'exact_quota_known':False,'stages':stage_reports,
            'scope':'Observed responses for these URLs, time and network only; short successful stages do not establish the website quota.',
            'output':str(out.resolve())}
        crawler.write_json(out/'rate_check_summary.json',summary)
        rows=[{k:r.get(k) for k in ('id','url','final_url','rate_check_stage','status','http_status','quality_status','error','raw_path')} for r in records.values()]
        buffer=io.StringIO(newline='');writer=csv.DictWriter(buffer,fieldnames=list(rows[0]) if rows else ['id','url','status','http_status'])
        writer.writeheader();writer.writerows(rows)
        crawler.atomic_bytes(out/'rate_check_results.csv',buffer.getvalue().encode('utf-8-sig'))
        lines=['# Long Chau rate check','',json.dumps(summary,ensure_ascii=False,indent=2),'',
            'Rate headers are observations, not a guarantee of quota. No proxy/IP rotation, parallel requests, gate reset or retry storm.']
        crawler.atomic_bytes(out/'RATE_CHECK_REPORT.md','\n'.join(lines).encode())
        temporary=Path(str(out)+'.zip.tmp');archive=Path(str(out)+'.zip')
        try:
            with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,allowZip64=True) as z:
                for p in sorted(out.rglob('*')):
                    if p.is_symlink():raise ValueError('Probe run contains a symlink.')
                    if p.is_file() and p.suffix not in ('.tmp','.lock') and '__pycache__' not in p.parts:
                        z.write(p,out.name+'/'+p.relative_to(out).as_posix())
            temporary.replace(archive)
        finally:temporary.unlink(missing_ok=True)
        print(json.dumps({'event':'rate_check_finished',**summary},ensure_ascii=False),flush=True)
    return summary


def run(samples,notebook,out,*,smoke=None,**options):
    if smoke is None: import check_longchau as smoke
    out=Path(out);runtime=out/'_runtime';runtime.mkdir(parents=True,exist_ok=True)
    smoke.unpack(notebook,runtime)
    tag=hashlib.sha256(str(runtime.resolve()).encode()).hexdigest()[:12]
    crawler=smoke.load('rate_core_'+tag,runtime/'crawler_snapshot.py')
    probe=smoke.load('rate_probe_'+tag,runtime/'priority_probe_snapshot.py')
    longchau=crawler.longchau_module()
    return measure(crawler,probe,longchau,samples,out,**options)


def main():
    import check_longchau as smoke
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=smoke.ROOT/'data/links_corpus_vi_en_zh.parquet')
    parser.add_argument('--notebook',type=Path,default=smoke.ROOT/'notebooks/crawl_corpus_kaggle_hf_upload.ipynb')
    parser.add_argument('--out',type=Path)
    parser.add_argument('--delays',type=float,nargs='+',default=[10.,7.5,5.])
    parser.add_argument('--urls-per-stage',type=int,default=20)
    parser.add_argument('--max-seconds',type=float,default=1200.)
    parser.add_argument('--cooldown-dir',type=Path,action='append',default=[])
    parser.add_argument('--share-cooldown-dir',type=Path)
    parser.add_argument('--respect-robots',action='store_true')
    args=parser.parse_args()
    stages=validate_stages([{'delay_seconds':d,'urls':args.urls_per_stage} for d in args.delays])
    samples,_=smoke.select(args.source,sum(s['urls'] for s in stages))
    out=args.out or smoke.ROOT/'runs'/('longchau_rate_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    run(samples,args.notebook,out,smoke=smoke,stages=stages,cooldown_dirs=args.cooldown_dir,share_cooldown_dir=args.share_cooldown_dir,
        max_seconds=args.max_seconds,respect_robots=args.respect_robots,environment='local_'+platform.system())


if __name__=='__main__':main()
