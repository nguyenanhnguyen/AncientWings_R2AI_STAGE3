"""Controlled ablations on an existing, completed single-GPU pipeline snapshot.

No crawling, translation generation, training or re-indexing. Each experiment
changes one factor relative to its named parent and writes a separate submission.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .common import storage
from .pipeline import Runner, run_lock


def option(command, name):
    return command[command.index(name) + 1]


def change(command, name, value=None, remove=False):
    command = list(command)
    if name in command:
        i = command.index(name)
        end = i + 1
        while end < len(command) and not command[end].startswith('--'):
            end += 1
        del command[i:end]
    if not remove:
        command.append(name)
        if value is not None:
            command.append(str(value))
    return command


def recorded(base, stage):
    state = storage.read_json(base / 'stages' / f'{stage}.json')
    for path, digest in state['outputs'].items():
        if not Path(path).is_file() or storage.sha256_file(path) != digest:
            raise ValueError(f'Baseline output missing/changed: {path}')
    command = state['command']
    if 'vibiomir.py' != Path(command[4]).name or command[5] != stage:
        raise ValueError('Require a completed pipeline using scripts/vibiomir.py.')
    return command[5:]


def definitions(suite):
    rows = [
        ('baseline', None, 'Replay baseline selection', {}, {}),
        ('window0', 'baseline', 'Keep indexed spans; no widening', {}, {'--window-tokens': '0'}),
        ('balanced', 'baseline', 'Selection profile balanced', {}, {'--profile': 'balanced'}),
        ('precision', 'baseline', 'Selection profile precision', {}, {'--profile': 'precision'}),
    ]
    if suite == 'overnight':
        rows += [
            ('rerank100', 'baseline', 'Score 100 candidates, keep original output budget',
             {'--rerank-k': '100'}, {}),
            ('no_card', 'baseline', 'Remove card fusion channel; same indexed subset',
             {'--doc-candidates': None}, {}),
            ('original_question', 'baseline', 'Rerank with Vietnamese question only',
             {'--match-language': None}, {}),
            ('feedback1', 'baseline', 'One lexical feedback pass from baseline reranking',
             {'--feedback-candidates': 'baseline'}, {}),
            ('feedback2', 'feedback1', 'Second feedback pass from feedback1 reranking',
             {'--feedback-candidates': 'feedback1'}, {}),
        ]
    return rows


def comparison(path, baseline):
    rows = storage.read_jsonl(path)
    overlaps, changed = [], 0
    for row in rows:
        old = baseline[int(row['query_id'])]['candidates']
        current = row['candidates']
        a, b = {c['chunk_id'] for c in old}, {c['chunk_id'] for c in current}
        overlaps.append(len(a & b) / max(len(a | b), 1))
        changed += ([c['chunk_id'] for c in old[:1]] != [c['chunk_id'] for c in current[:1]])
    return {'candidate_jaccard_vs_baseline': sum(overlaps) / max(len(overlaps), 1),
            'top1_changed_vs_baseline': changed}


def run(args):
    base, out = Path(args.base).resolve(), Path(args.out).resolve()
    if out == base or out.is_relative_to(base) or base.is_relative_to(out):
        raise ValueError('--out must be separate from the baseline directory.')
    retrieve, submit = recorded(base, 'retrieve'), recorded(base, 'submit')
    if option(retrieve, '--shards') != '1':
        raise ValueError('This experiment runner currently requires a single-query-shard baseline.')
    if '--feedback-candidates' in retrieve:
        raise ValueError('Start from a baseline without feedback.')
    baseline_candidates = Path(option(submit, '--candidates'))
    if baseline_candidates != Path(option(retrieve, '--out')) / 'candidates.jsonl':
        raise ValueError('Submission must use the recorded retrieval output.')
    manifest = storage.read_json(baseline_candidates.with_name('retrieval_manifest.json'))
    for flag, key in [('--chunks', 'chunks_sha256'), ('--queries', 'queries_sha256')]:
        if storage.sha256_file(option(retrieve, flag)) != manifest.get(key):
            raise ValueError(f'Baseline {flag} changed since retrieval.')
    prepare_state = base / 'stages/prepare.json'
    if prepare_state.exists():
        corpus = option(submit, '--corpus')
        digest = storage.read_json(prepare_state)['outputs'].get(corpus)
        if digest != storage.sha256_file(corpus):
            raise ValueError('Frozen baseline corpus changed since prepare.')
    index = Path(option(retrieve, '--index'))
    inputs = [Path(option(retrieve, flag)) for flag in
              ('--chunks', '--queries', '--translations', '--doc-candidates') if flag in retrieve]
    inputs += sorted(p for p in index.iterdir() if p.is_file())
    inputs += [baseline_candidates, Path(option(submit, '--corpus'))]
    if '--links' in submit:
        inputs.append(Path(option(submit, '--links')))
    if '--calibration' in submit:
        inputs.append(Path(option(submit, '--calibration')))
    rows = definitions(args.suite)
    plan = {'base': str(base), 'retrieve': retrieve, 'submit': submit,
            'inputs': {str(p): storage.sha256_file(p) for p in inputs},
            'experiments': rows, 'labels': str(Path(args.labels).resolve()) if args.labels else None,
            'labels_sha256': storage.sha256_file(args.labels) if args.labels else None}
    out.mkdir(parents=True, exist_ok=True)
    with run_lock(out / 'experiments.lock'):
        plan_path = out / 'plan.json'
        if plan_path.exists() and storage.read_json(plan_path) != json.loads(json.dumps(plan)):
            raise ValueError('Experiment inputs/options changed; choose a new --out.')
        if not args.dry_run:
            storage.write_json(plan_path, plan)
        runner = Runner(out, dry_run=args.dry_run)
        cache = out / 'scores.sqlite'
        source_cache = Path(option(retrieve, '--out')) / 'scores.sqlite'
        if not args.dry_run and not cache.exists() and source_cache.exists():
            # SQLite backup also sees WAL transactions; copying the .sqlite alone does not.
            temporary = out / 'scores.seed.sqlite'
            with closing(sqlite3.connect(source_cache.as_uri() + '?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(temporary)) as target:
                    source.backup(target)
            temporary.replace(cache)
        paths, report = {'baseline': baseline_candidates}, []
        reference = {int(r['query_id']): r for r in storage.iter_jsonl(baseline_candidates)}
        for name, parent, description, retrieval_changes, submit_changes in rows:
            directory = out / name
            candidates = baseline_candidates
            if retrieval_changes:
                target = directory / 'retrieval'
                candidates = target / 'candidates.jsonl'
                command = change(change(retrieve, '--out', target), '--score-cache', cache)
                dependencies = list(inputs)
                for flag, value in retrieval_changes.items():
                    if flag == '--feedback-candidates':
                        value = paths[value]
                        dependencies += [value, value.with_name('retrieval_manifest.json')]
                    command = change(command, flag, value, remove=value is None)
                outputs = [candidates, target / 'retrieval_manifest.json']
                if '--feedback-candidates' in command:
                    outputs.append(target / 'feedback_trace.jsonl')
                runner.step(name + '_retrieve', command, dependencies, outputs)
            paths[name] = candidates
            destination = directory / 'submission'
            command = change(change(submit, '--out', destination), '--candidates', candidates)
            for flag, value in submit_changes.items():
                command = change(command, flag, value)
            # Guarantee a predictable name even when baseline used a custom filename.
            command = change(command, '--name', 'submission.json')
            runner.step(name + '_submit', command, inputs + [candidates],
                        [destination / f'submission.{ext}' for ext in ('json', 'zip')]
                        + [destination / 'submission_manifest.json'])
            if args.labels:
                runner.step(name + '_evaluate', ['evaluate', 'score', '--submission',
                            destination / 'submission.json', '--labels', args.labels,
                            '--candidates', candidates, '--corpus', option(submit, '--corpus'),
                            '--out', directory / 'evaluation'],
                            inputs + [Path(args.labels), candidates, destination / 'submission.json'],
                            [directory / 'evaluation/metrics.json'])
            if not args.dry_run:
                manifest = storage.read_json(destination / 'submission_manifest.json')
                item = {'name': name, 'parent': parent, 'change': description,
                        'zip': str(destination / 'submission.zip'),
                        'submission': manifest['submission'], **comparison(candidates, reference)}
                if args.labels:
                    item['evaluation'] = storage.read_json(directory / 'evaluation/metrics.json')
                timing = out / 'stages' / (name + '_retrieve.json')
                if timing.exists():
                    item['retrieval_seconds'] = storage.read_json(timing)['seconds']
                    details = storage.read_json(candidates.with_name('retrieval_manifest.json'))
                    item['cache_hits'] = details.get('cache_hits')
                    item['cache_misses'] = details.get('cache_misses')
                report.append(item)
                storage.write_json(out / 'summary.json', report)
                lines = ['# Experiment results', '',
                         'No labels: output differences are NOT quality gains.' if not args.labels
                         else 'Metrics are measured only on the supplied labels; inspect label_sources.', '',
                         '| Experiment | Parent | Changed top 1 | Candidate Jaccard | ZIP |',
                         '|---|---|---:|---:|---|']
                for r in report:
                    lines.append(f"| {r['name']} | {r['parent'] or '-'} | "
                                 f"{r['top1_changed_vs_baseline']} | "
                                 f"{r['candidate_jaccard_vs_baseline']:.4f} | "
                                 f"[{r['name']}]({r['name']}/submission/submission.zip) |")
                (out / 'RESULTS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Experiments {"previewed" if args.dry_run else "completed"}: {out}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='work/run_local_100k')
    parser.add_argument('--out', default='work/ablation_100k')
    parser.add_argument('--suite', choices=['selection', 'overnight'], default='overnight')
    parser.add_argument('--labels', help='Optional human/gold validation labels; never generated here.')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    run(args)


if __name__ == '__main__':
    main()
