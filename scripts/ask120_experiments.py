"""Offline A/B experiments embedded in the 120ask check notebook.

Candidate patches are written into a separate experiment directory. Production
parser/gate files and real manual-review labels are never modified.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import base64
import csv
import difflib
import gzip
import importlib.util
import json
from pathlib import Path
import shutil
import zlib
from unittest.mock import patch


def prepare(gate, run_dir, experiment_dir):
    """Compare frozen pre-fix sources against current production source in isolation."""
    root = Path(experiment_dir)
    root.mkdir(parents=True, exist_ok=False)
    variant_dir = root / 'suggested_patch'
    variant_dir.mkdir()
    baseline_dir=root/'baseline'
    baseline_dir.mkdir()
    archived=json.loads(Path(__file__).with_name('ask120_experiment_baseline.json').read_text(encoding='utf-8'))
    for name,entry in archived['files'].items():
        if name not in ('ask120_gate.py','ask120_snapshot.py'):raise ValueError('Unexpected baseline file')
        body=zlib.decompress(base64.b85decode(entry['zlib_base85']))
        if gate.sha(body)!=entry['sha256']:raise ValueError('Baseline snapshot hash mismatch')
        (baseline_dir/name).write_bytes(body)
    spec_base=importlib.util.spec_from_file_location('ask120_experiment_baseline',baseline_dir/'ask120_gate.py')
    baseline=importlib.util.module_from_spec(spec_base)
    spec_base.loader.exec_module(baseline)
    gate_source = (baseline_dir/'ask120_gate.py').read_text(encoding='utf-8')
    parser_source = (baseline_dir/'ask120_snapshot.py').read_text(encoding='utf-8')
    fixed_gate = Path(gate.__file__).read_text(encoding='utf-8')
    fixed_parser = Path(gate.PARSER.__file__).read_text(encoding='utf-8')
    for name, text in [('ask120_gate.py', fixed_gate), ('ask120_snapshot.py', fixed_parser)]:
        compile(text, name, 'exec')
        (variant_dir / name).write_text(text, encoding='utf-8')
    (root/'baseline_gate.py').write_text(gate_source, encoding='utf-8')
    (root/'baseline_parser.py').write_text(parser_source, encoding='utf-8')
    proposed_diff = ''.join(difflib.unified_diff(gate_source.splitlines(keepends=True),
        fixed_gate.splitlines(keepends=True), fromfile='a/scripts/ask120_gate.py', tofile='b/scripts/ask120_gate.py'))
    proposed_diff += ''.join(difflib.unified_diff(parser_source.splitlines(keepends=True),
        fixed_parser.splitlines(keepends=True), fromfile='a/scripts/ask120.py', tofile='b/scripts/ask120.py'))
    (root/'suggested.patch').write_text(proposed_diff, encoding='utf-8')
    spec = importlib.util.spec_from_file_location('ask120_experiment_candidate', variant_dir/'ask120_gate.py')
    candidate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidate)
    metadata = {'experiment_only': True, 'run_dir': str(Path(run_dir).resolve()),
        'baseline_gate_sha256': gate.sha((baseline_dir/'ask120_gate.py').read_bytes()),
        'baseline_parser_sha256': gate.sha((baseline_dir/'ask120_snapshot.py').read_bytes()),
        'candidate_gate_sha256': gate.sha((variant_dir/'ask120_gate.py').read_bytes()),
        'candidate_parser_sha256': gate.sha((variant_dir/'ask120_snapshot.py').read_bytes())}
    gate.write_json(root/'experiment_manifest.json', metadata)
    return {'baseline':baseline, 'candidate':candidate, 'root':root, 'run_dir':Path(run_dir),
            'results':{}, 'network_attempts':0, 'metadata':metadata}


@contextmanager
def offline(context):
    """Any Requests call inside an experiment is a failing assertion."""
    def denied(*args, **kwargs):
        context['network_attempts'] += 1
        raise AssertionError('Experiment attempted a network request')
    with patch('requests.sessions.Session.request', side_effect=denied):
        yield


def read_rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def remember(context, name, rows):
    context['results'][name] = rows
    context['baseline'].write_json(context['root']/(name+'.json'), rows)
    return rows


def manual_review_ab(context):
    """Use real records, synthetic labels, and a compact regression-complete cohort."""
    base = context['baseline']
    run = context['run_dir']
    pages = base.read_jsonl_bytes((run/'results_reparsed.jsonl').read_bytes())
    selected = {p['id']:p for p in pages if p['url'].split('/')[-1].split('.')[0] in base.REGRESSIONS}
    ordinary = []
    for p in pages:
        if p['id'] in selected:
            continue
        clean = [t for t in p.get('thread_decisions', []) if t['corpus_decision']=='INCLUDE'
                 and not t['decision_reasons'] and not t['source_flags'] and not t['parser_flags']]
        if clean:
            selected[p['id']] = p
            ordinary.extend(clean)
        if len(ordinary) >= 60:
            break
    if len(ordinary) < 50 or len(selected) < len(base.REGRESSIONS):
        raise ValueError('Manual experiment requires all regression pages and >=50 ordinary INCLUDE threads')
    all_samples = base.read_jsonl_bytes((run/'sample.jsonl').read_bytes())
    cases = []
    with offline(context):
        for version in ('baseline', 'candidate'):
            engine = context[version]
            shadow = context['root']/('manual_'+version)
            (shadow/'records').mkdir(parents=True)
            manifest = json.loads((run/'manifest.json').read_text(encoding='utf-8'))
            manifest.update(experiment_only=True, selected=len(selected), policy=dict(engine.POLICY),
                policy_sha256=engine.policy_hash(engine.POLICY),
                gate_sha256=engine.sha(Path(engine.__file__).read_bytes()),
                parser_sha256=engine.sha(Path(engine.PARSER.__file__).read_bytes()))
            engine.write_json(shadow/'manifest.json', manifest)
            engine.jsonl(shadow/'sample.jsonl', [s for s in all_samples if s['id'] in selected])
            # A real copy preserves raw paths while keeping all mutations in the experiment.
            for p in selected.values():
                if p.get('raw_path'):
                    destination = shadow/p['raw_path']
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(run/p['raw_path'], destination)
                body=engine.safe_raw(engine.RunInput(shadow),p)
                parsed=engine.parse_source_response(body,dict(p,parser_sha256=manifest['parser_sha256'],
                    policy_sha256=manifest['policy_sha256']))
                parsed['essential_media_missing']=bool(parsed.get('question_media')) or '图片涉及用户隐私' in parsed['ask120_question_raw']
                parsed['thread_decisions']=[engine.review_thread(t,parsed,manifest['policy']) for t in parsed['ask120_threads']]
                parsed.update(engine.decide_page(parsed['thread_decisions'],parsed))
                engine.write_json(shadow/'records'/f"{p['id']}.json",parsed)
            initial = engine.build_outputs(shadow, export_candidates=False)
            rows = read_rows(shadow/'manual_review_sheet.csv')
            subject = next(r for r in rows if int(r['source_id']) not in
                {p['id'] for p in selected.values() if p['url'].split('/')[-1].split('.')[0] in base.REGRESSIONS}
                and r['corpus_decision']=='INCLUDE' and r['decision_reasons']=='[]')
            subject.update(reviewer_decision='EXCLUDE', reviewer_notes='PARSER_ERROR: synthetic experiment label.',
                           reviewed_at='2026-10-20T12:00:00+07:00')
            labels = shadow/'synthetic_labels.csv'
            engine.save_csv(labels, rows, list(rows[0]))
            after = engine.build_outputs(shadow, manual_review_path=labels, export_candidates=False)
            retained = any(r['source_id']==subject['source_id'] and r['thread_id']==subject['thread_id']
                           for r in read_rows(shadow/'manual_review_sheet.csv'))
            subject['raw_sha256'] = 'intentionally-stale'
            engine.save_csv(labels, rows, list(rows[0]))
            try:
                engine.build_outputs(shadow, manual_review_path=labels, export_candidates=False)
                stale_rejected = False
            except ValueError as exc:
                stale_rejected = 'Stale manual' in str(exc)
            cases.append({'version':version, 'pages':len(selected), 'initial_readiness':initial['readiness'],
                'source_id':int(subject['source_id']), 'thread_id':subject['thread_id'],
                'labeled_error_retained':retained, 'readiness_after_parser_error':after['readiness'],
                'stale_label_rejected':stale_rejected,
                'passed':retained and after['readiness']=='NEEDS_PARSER_FIX' and stale_rejected})
    assert cases[1]['passed'], cases
    return remember(context, 'manual_review_ab', cases)


def fixture_html(question='A real patient question with sufficient context.', answer=None, fallback=False):
    answer = answer or 'This is a sufficiently detailed source answer for checking extraction and admission.'
    question_node = (f'<div class="b_askbox"><div class="b_askcont">{question}</div></div>'
                     if fallback else f'<div id="d_msCon">{question}</div>')
    return (f'<html><meta charset="utf-8"><h1 id="d_askH1">Patient question</h1>{question_node}'
        f'<span>1人回复</span><div class="b_answerbox"><div class="b_answerli">'
        '<div class="b_answertl"><span class="b_sp1"><a>Fixture responder</a> 医师</span></div>'
        f'<div class="b_anscont_cont"><p id="reply123">{answer}</p></div></div></div></html>').encode()


def write_fixture(engine, source, body, **updates):
    (source/'raw').mkdir(parents=True, exist_ok=True)
    engine.write_json(source/'manifest.json', {'fixture':True})
    sample = {'id':1, 'url':'https://www.120ask.com/question/123.htm'}
    engine.jsonl(source/'sample.jsonl', [sample])
    (source/'raw/1.gz').write_bytes(gzip.compress(body, mtime=0))
    record = dict(sample, http_status=200, content_type='text/html; charset=utf-8',
                  raw_path='raw/1.gz', raw_sha256=engine.sha(body))
    record.update(updates)
    engine.write_json(source/'records/1.json', record)


def resume_ab(context):
    rows = []
    mutations = ('unchanged','raw_and_hash','final_url','content_type','http_status','output_raw_missing','source_hash_invalid')
    with offline(context):
        for version in ('baseline','candidate'):
            engine = context[version]
            for mutation in mutations:
                case_dir = context['root']/('resume_'+version)/mutation
                source, output = case_dir/'input', case_dir/'output'
                write_fixture(engine, source, fixture_html())
                engine.replay(source, output)
                checkpoint = output/'records/1.json'
                first = checkpoint.read_bytes()
                old = json.loads((source/'records/1.json').read_text(encoding='utf-8'))
                if mutation=='raw_and_hash':
                    write_fixture(engine, source, fixture_html(answer='A changed answer, sufficiently long and different from the original answer.'))
                elif mutation in ('final_url','content_type','http_status'):
                    old[mutation] = {'final_url':'https://www.120ask.com/question/456.htm',
                        'content_type':'text/html; charset=gb18030', 'http_status':403}[mutation]
                    engine.write_json(source/'records/1.json', old)
                elif mutation=='output_raw_missing':
                    # Remove only a single generated experiment fixture file.
                    (output/json.loads(first)['raw_path']).unlink()
                elif mutation=='source_hash_invalid':
                    old['raw_sha256'] = '0'*64
                    engine.write_json(source/'records/1.json', old)
                rejected = False
                parse_calls = 0
                try:
                    with patch.object(engine, 'parse_source_response', wraps=engine.parse_source_response) as parse:
                        engine.replay(source, output)
                        parse_calls = parse.call_count
                except ValueError as exc:
                    rejected = 'Checkpoint source evidence changed' in str(exc) or 'Replay identity changed' in str(exc)
                saved = json.loads(checkpoint.read_text(encoding='utf-8'))
                if mutation=='unchanged':
                    passed = not rejected and parse_calls==0 and checkpoint.read_bytes()==first
                elif mutation=='output_raw_missing':
                    passed = not rejected and parse_calls==1 and (output/saved['raw_path']).exists()
                elif mutation=='source_hash_invalid':
                    passed = rejected or saved['corpus_decision']=='EXCLUDE'
                else:
                    passed = rejected and checkpoint.read_bytes()==first
                rows.append({'version':version,'mutation':mutation,'rejected':rejected,
                    'parse_calls':parse_calls,'checkpoint_unchanged':checkpoint.read_bytes()==first,
                    'saved_decision':saved['corpus_decision'],'passed':passed})
    assert all(r['passed'] for r in rows if r['version']=='candidate'), rows
    return remember(context, 'resume_ab', rows)


def media_ab(context):
    cases = [
        ('text_only','A real patient question with sufficient context.','INCLUDE',False),
        ('medical_image','Please interpret this medical image: <img src="/lab.jpg">','REVIEW',False),
        ('lazy_image','Please interpret the report: <img data-src="/lab.jpg">','REVIEW',False),
        ('private_placeholder','图片涉及用户隐私 <img src="/ystp.jpg">','REVIEW',False),
        ('decorative_uncertain','A real patient question. <img src="/icon.png" alt="">','REVIEW',False),
        ('fallback_template','Please interpret the image: <img src="/lab.jpg">','REVIEW',True),
    ]
    rows = []
    with offline(context):
        for version in ('baseline','candidate'):
            engine = context[version]
            for name, question, expected, fallback in cases:
                body = fixture_html(question, fallback=fallback)
                fixture_dir = context['root']/('media_'+version)/name
                write_fixture(engine, fixture_dir/'input', body)
                engine.replay(fixture_dir/'input', fixture_dir/'output')
                p = json.loads((fixture_dir/'output/records/1.json').read_text(encoding='utf-8'))
                rows.append({'version':version,'case':name,'expected':expected,
                    'actual':p['corpus_decision'], 'question_attachment_urls':p.get('question_attachment_urls',[]),
                    'media_evidence_count':len(p.get('question_media',[])),
                    'passed':p['corpus_decision']==expected})
    assert all(r['passed'] for r in rows if r['version']=='candidate'), rows
    return remember(context, 'media_ab', rows)


def impact_replay(context):
    """Reparse every saved byte with candidate sources; compare candidate text and IDs."""
    base, candidate = context['baseline'], context['candidate']
    run = context['run_dir']
    manifest = json.loads((run/'manifest.json').read_text(encoding='utf-8'))
    policy = dict(candidate.POLICY)
    baseline_policy = dict(base.POLICY)
    before = base.read_jsonl_bytes((run/'results_reparsed.jsonl').read_bytes())
    if not (run/'corpus_candidates.jsonl').read_bytes():
        raise ValueError('Impact experiment requires EXPORT_CANDIDATE_CORPUS=True')
    reader = base.RunInput(run)
    before_docs={}
    after, docs, changed, image_pages = [], {}, [], []
    with offline(context):
        for i, original in enumerate(before, 1):
            body = base.safe_raw(reader, original)
            metadata = {k:original.get(k) for k in ('id','url','final_url','content_type','http_status',
                'raw_path','raw_sha256','access_status')}
            metadata.update(parser_sha256=context['metadata']['candidate_parser_sha256'],
                            policy_sha256=candidate.policy_hash(policy))
            previous=base.parse_source_response(body,dict(metadata,
                parser_sha256=context['metadata']['baseline_parser_sha256'],
                policy_sha256=base.policy_hash(baseline_policy)))
            previous['essential_media_missing']='图片涉及用户隐私' in previous['ask120_question_raw']
            previous['thread_decisions']=[base.review_thread(t,previous,baseline_policy) for t in previous['ask120_threads']]
            previous.update(base.decide_page(previous['thread_decisions'],previous))
            previously_included=[t for t in previous['thread_decisions'] if t['corpus_decision']=='INCLUDE']
            if previously_included:
                before_docs[previous['id']]=base.build_candidate_document(previous,previously_included)
            p = candidate.parse_source_response(body, metadata)
            p['essential_media_missing'] = bool(p.get('question_media')) or '图片涉及用户隐私' in p['ask120_question_raw']
            p['thread_decisions'] = [candidate.review_thread(t,p,policy) for t in p['ask120_threads']]
            p.update(candidate.decide_page(p['thread_decisions'],p))
            after.append(p)
            included = [t for t in p['thread_decisions'] if t['corpus_decision']=='INCLUDE']
            if included:
                docs[p['id']] = candidate.build_candidate_document(p,included)
            if p['corpus_decision']!=previous['corpus_decision']:
                changed.append({'id':p['id'],'before':previous['corpus_decision'],'after':p['corpus_decision']})
            if p.get('question_media'):
                image_pages.append({'id':p['id'],'decision':p['corpus_decision'],'question_media':p['question_media']})
            if i%250==0:
                print(f'Candidate impact replay: {i}/{len(before)}', flush=True)
    reader.close()
    regression = candidate.validate_regressions({p['id']:p for p in after})
    common = set(before_docs)&set(docs)
    changed_text = [key for key in common if before_docs[key]['text']!=docs[key]['text']]
    violations = [d['id'] for d in docs.values() if candidate.PARSER.AUDIO_FALLBACK.search(d['text'])
                  or candidate.PARSER.LEGACY_MARKUP.search(d['text']) or candidate.CORRUPT.search(d['text'])]
    result = {'pages':len(after),'raw_verified':len(after), 'before_candidate_documents':len(before_docs),
        'after_candidate_documents':len(docs),'removed_candidate_ids':sorted(set(before_docs)-set(docs)),
        'added_candidate_ids':sorted(set(docs)-set(before_docs)), 'changed_candidate_text_ids':changed_text,
        'changed_page_decisions':changed, 'after_page_decisions':dict(Counter(p['corpus_decision'] for p in after)),
        'question_media_pages':len(image_pages), 'regressions':regression,
        'candidate_invariant_violations':violations,
        'passed':len(after)==len(before) and all(r['passed'] for r in regression.values()) and not violations}
    base.jsonl(context['root']/'candidate_impact_pages.jsonl', after)
    base.write_json(context['root']/'question_media_audit.json', image_pages)
    assert result['passed'], result
    return remember(context, 'impact_replay', result)


def report(context):
    results = context['results']
    required = {'manual_review_ab','resume_ab','media_ab','impact_replay'}
    if set(results)!=required:
        raise ValueError('Run all experiment cells before generating the report')
    if context['network_attempts']:
        raise AssertionError('An experiment attempted a network request')
    lines = ['# 120ask — thí nghiệm A/B và hướng sửa', '',
        'Nhãn thủ công dùng trong thí nghiệm là nhãn tổng hợp để kiểm tra luồng, không phải review nội dung thật.', '',
        '| Thí nghiệm | Baseline đạt | Bản sửa thử đạt |', '|---|---:|---:|']
    for name in ('manual_review_ab','resume_ab','media_ab'):
        rows = results[name]
        counts = {v:(sum(r['passed'] for r in rows if r['version']==v),sum(r['version']==v for r in rows))
                  for v in ('baseline','candidate')}
        lines.append(f"| {name} | {counts['baseline'][0]}/{counts['baseline'][1]} | {counts['candidate'][0]}/{counts['candidate'][1]} |")
    impact = results['impact_replay']
    lines += ['', '## Tác động trên raw thật', '',
        json.dumps(impact,ensure_ascii=False,indent=2), '', '## Nên sửa theo thứ tự', '',
        '1. P1 — Đã giữ mọi nhãn có quyết định đã xác thực, tính PARSER_ERROR trên toàn bộ nhãn hợp lệ, '
        'và lưu cohort review theo parser/gate/policy/sample hash để không mất mục cũ khi chọn mẫu thay thế.', '',
        '2. P2 — Resume: so ID/URL/final URL/content type/HTTP status/raw hash với checkpoint trước khi skip. '
        'Nếu khác, từ chối và yêu cầu run mới; nếu raw bản output thiếu/hỏng thì tái tạo từ source đã kiểm hash. '
        'Nhánh crawl_new cũng kiểm fetch checkpoint và raw, dùng lại fetch sau interrupt mà không gửi request mới.', '',
        '3. P2 — Parser lưu media của câu hỏi (URL, DOM locator, alt, cả lazy attributes); gate chuyển REVIEW khi '
        'còn phụ thuộc media. Không tự bỏ qua ảnh được cho là trang trí nếu chưa có bằng chứng template. '
        'Đã đồng bộ field với raw audit và cả replay/crawl; có hỗ trợ srcset. Media CSS cần mẫu/template riêng.', '',
        '4. Source hiện tại được nhúng vào candidate để đối chiếu baseline V3 đóng băng; '
        'hoàn tất manual review trước khi xác nhận corpus. Không đổi policy để tăng số accepted.', '',
        f"Requests attempts trong các thí nghiệm: {context['network_attempts']}.", '',
        'Candidate trong suggested_patch/ là bản sao source đã sửa; baseline V3 chỉ dùng cho thí nghiệm. '
        'Không dùng checkpoint hoặc nhãn thí nghiệm để tiếp tục run production.', '',
        '## Provenance', '', json.dumps(context['metadata'],ensure_ascii=False,indent=2)]
    output = context['root']/'experiment_report.md'
    output.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    context['baseline'].write_json(context['root']/'experiment_results.json',
        {'metadata':context['metadata'],'network_attempts':context['network_attempts'],'results':results})
    return output
