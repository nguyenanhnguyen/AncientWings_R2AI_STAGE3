"""Offline replay diff and holdout review for a frozen ask39 parser/gate."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import difflib
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import shutil


def load(name, directory):
    spec = importlib.util.spec_from_file_location('_f5_'+name,Path(directory)/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()]


def write_json(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def fingerprint(directory):
    return {name:hashlib.sha256((Path(directory)/name).read_bytes()).hexdigest()
            for name in ('ask39.py','ask39_gate.py','ask39_audit.py')}


def replay(baseline, output, code_dir):
    baseline, output = Path(baseline).resolve(),Path(output).resolve()
    if output.exists(): raise ValueError('Replay output already exists')
    parser,gate,audit = [load(name,code_dir) for name in ('ask39','ask39_gate','ask39_audit')]
    sample = read_jsonl(baseline/'sample.jsonl')
    previous = {r['id']:r for r in read_jsonl(baseline/'results.jsonl')}
    if len(sample)!=50 or len(previous)!=50: raise ValueError('Expected original 50-page baseline')
    output.mkdir(parents=True)
    (output/'records').mkdir();(output/'diffs').mkdir()
    records,sources,diffs = [],{},[]
    for row in sample:
        old = previous[row['id']]
        raw_path=(baseline/old['raw_path']).resolve()
        if not raw_path.is_relative_to(baseline): raise ValueError('Raw path outside baseline')
        body=gzip.decompress(raw_path.read_bytes())
        if hashlib.sha256(body).hexdigest()!=old['raw_sha256']: raise ValueError('Baseline raw hash mismatch')
        doc=parser.extract(body,old.get('final_url') or row['url'],old.get('content_type','text/html'))
        record=dict(old,**doc)
        destination=output/old['raw_path'];destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(raw_path,destination)
        records.append(record)
        sources[row['id']]=dict(id=row['id'],url=row['url'],raw_sha256=old['raw_sha256'])
        before=audit.audit_record(old,body);after=audit.audit_record(record,body)
        diff=dict(id=row['id'],url=row['url'],baseline_chars=len(old.get('text','')),candidate_chars=len(record['text']),
            source_answers=after['source_answers'],source_followups=after['source_followup_blocks'],
            missing_answers_before=before['missing_answers'],missing_answers_after=after['missing_answers'],
            missing_followups_before=before['missing_followup_blocks'],missing_followups_after=after['missing_followup_blocks'],
            baseline_qc=old.get('quality_status'),candidate_parser_flags=record['parser_flags'],
            audit_flags=after['flags'],dom_exclusions=len(record['dom_exclusions']))
        diffs.append(diff)
        (output/'records'/f"{row['id']}.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        delta=difflib.unified_diff(old.get('text','').splitlines(),record['text'].splitlines(),fromfile='trafilatura',tofile=parser.VERSION,lineterm='')
        (output/'diffs'/f"{row['id']}.diff").write_text('\n'.join(delta)+'\n',encoding='utf-8')
    exported=gate.export_candidates(records,output,output/'candidate.parquet',sources)
    decisions={r['id']:r for r in read_jsonl(output/'candidate.decisions.jsonl')}
    for diff in diffs:
        decision=decisions[diff['id']]
        diff.update(candidate_qc=decision['quality_status'],candidate_eligible=decision['candidate_eligible'],
                    decision_reasons=decision['quality_flags'])
    with (output/'baseline_candidate_diff.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(diffs[0]));writer.writeheader()
        writer.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,list) else v for k,v in d.items()} for d in diffs)
    summary=dict(pages=len(records),source_answers=sum(d['source_answers'] for d in diffs),
        source_followups=sum(d['source_followups'] for d in diffs),
        missing_answers_before=sum(d['missing_answers_before'] for d in diffs),
        missing_answers_after=sum(d['missing_answers_after'] for d in diffs),
        missing_followups_before=sum(d['missing_followups_before'] for d in diffs),
        missing_followups_after=sum(d['missing_followups_after'] for d in diffs),
        audit_flags=dict(Counter(f for d in diffs for f in d['audit_flags'])),export=exported,
        baseline=str(baseline),code_sha256=fingerprint(code_dir))
    write_json(output/'summary.json',summary);write_json(output/'source_evidence.json',sources)
    return summary


def review_holdout(run, baseline, code_dir, expected=200):
    run,baseline=Path(run),Path(baseline)
    sample=read_jsonl(run/'sample.jsonl');old=read_jsonl(baseline/'sample.jsonl')
    if len(sample)!=expected or len({r['id'] for r in sample})!=expected or len({r['url'] for r in sample})!=expected:
        raise ValueError('Wrong holdout size or duplicated IDs/URLs')
    if {r['id'] for r in sample}&{r['id'] for r in old} or {r['url'] for r in sample}&{r['url'] for r in old}:
        raise ValueError('Holdout overlaps baseline')
    summary=json.loads((run/'summary.json').read_text(encoding='utf-8'))
    records={r['id']:r for r in read_jsonl(run/'results.jsonl')}
    decisions={r['id']:r for r in read_jsonl(run/'candidate.decisions.jsonl')}
    if len(records)!=expected or not summary['complete']: raise ValueError('Holdout crawl incomplete')
    audit=load('ask39_audit',code_dir)
    groups=defaultdict(Counter);source_counts=Counter();parser_flags=Counter();audit_flags=Counter()
    audits=[];templates=defaultdict(list)
    for row in sample:
        record,decision=records[row['id']],decisions[row['id']]
        strata=row['sampling_stratum']
        groups[strata]['pages']+=1
        groups[strata]['candidate' if decision['candidate_eligible'] else 'review']+=1
        groups[strata]['extraction_accepted']+=decision['extraction_status']=='accepted'
        parser_flags.update(decision['parser_flags']);audit_flags.update(decision['audit_flags']);source_counts.update(decision['source_flags'])
        if record.get('raw_path'):
            path=(run/record['raw_path']).resolve()
            if not path.is_relative_to(run.resolve()): raise ValueError('Raw path outside run')
            body=gzip.decompress(path.read_bytes())
            if hashlib.sha256(body).hexdigest()!=record.get('raw_sha256'): raise ValueError('Holdout raw hash mismatch')
            check=audit.audit_record(record,body);audits.append(check)
        shape=(record.get('main_answer_count',0),bool(record.get('followup_count')),bool(any(a.get('rule')=='recover_nested_paragraphs' for a in record.get('normalization_actions',[]))),record.get('declared_encoding'))
        templates[str(shape)].append(row['id'])
    accepted=sorted(r['id'] for r in decisions.values() if r['candidate_eligible'])
    chosen=random.Random(20261022).sample(accepted,min(20,len(accepted)))
    reasons=defaultdict(list)
    for ident,d in decisions.items():
        if not d['candidate_eligible']: reasons[ident].append('review_or_error')
    for ident in chosen: reasons[ident].append('random_accepted_seed20261022')
    for ids in templates.values(): reasons[sorted(ids)[0]].append('template_representative')
    lines=['# F5 source/candidate review packet','','Selection is automated; no human labels are implied.']
    for ident in sorted(reasons):
        record,decision=records[ident],decisions[ident]
        lines.extend(['',f'## {ident}: {record.get("title","")}',record['url'],
                      'Selection: '+', '.join(reasons[ident]),
                      'Decision: '+json.dumps({k:decision[k] for k in ('extraction_status','quality_status','parser_flags','audit_flags','source_flags')},ensure_ascii=False),
                      'Source evidence: '+json.dumps(decision.get('source_evidence',[]),ensure_ascii=False),
                      '', '### Candidate text','',record.get('text','')])
        for answer in record.get('answers',[]):
            lines.extend(['',f"Answer {answer['answer_id']} | header: {answer.get('author_header_raw','')}",
                          'Body locator: '+', '.join(answer.get('body_locators',[])),
                          'Source body: '+answer.get('source_text','')])
            for message in answer.get('followups',[]):
                lines.extend([f"Follow-up {message.get('source_message_id')}: {message['speaker_role']} / {message['parent_answer_id']}",message['source_text']])
    (run/'f5_review_packet.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    result=dict(expected=expected,attempted=len(records),baseline_overlap=0,
        strata={k:dict(v) for k,v in groups.items()},candidate_exported=len(accepted),review=expected-len(accepted),
        extraction_accepted=sum(d['extraction_status']=='accepted' for d in decisions.values()),
        source_answers=sum(r.get('main_answer_count',0) for r in records.values()),
        followup_messages=sum(r.get('followup_count',0) for r in records.values()),
        parser_flags=dict(parser_flags),audit_flags=dict(audit_flags),source_flags=dict(source_counts),
        independent_audit_flags=dict(Counter(f for r in audits for f in r['flags'])),
        template_groups={k:len(v) for k,v in templates.items()},review_packet_ids=sorted(reasons),
        random_accepted_ids=chosen,code_sha256=fingerprint(code_dir),
        readiness='NEEDS_FIX' if parser_flags or audit_flags or any(r['flags'] for r in audits) else 'PENDING_SAMPLE_REVIEW')
    review_path=run/'f5_assistant_review.json'
    if review_path.is_file():
        review=json.loads(review_path.read_text(encoding='utf-8'))
        result['assistant_review_findings']=review.get('findings',[])
        result['human_labels']=False
        if review.get('release_blocked') or review.get('findings'): result['readiness']='NEEDS_FIX'
    write_json(run/'f5_holdout_summary.json',result)
    (run/'f5_independent_audit.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in audits),encoding='utf-8')
    return result


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('replay','review_holdout'))
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--run',type=Path,required=True,help='New replay output or completed holdout directory')
    parser.add_argument('--code-dir',type=Path,default=Path(__file__).parent)
    args=parser.parse_args()
    result=(replay(args.baseline,args.run,args.code_dir) if args.mode=='replay'
            else review_holdout(args.run,args.baseline,args.code_dir))
    print(json.dumps(result,ensure_ascii=False,indent=2))
