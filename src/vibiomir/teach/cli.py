"""Block T CLI: vibiomir.py teach {sample|generate|mine|judge|train} ..."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main(argv=None):
    from . import mine, sample, store, teacher, train

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    push = commands.add_parser('push', help='Đẩy code + input lên HF dataset private cho Kaggle')
    push.add_argument('--hub-repo', required=True)
    push.add_argument('files', nargs='+', help='e.g. work/teach/seeds.jsonl chunks.parquet')
    push.set_defaults(handler=lambda a: store.push_inputs(a.hub_repo, ROOT, a.files))
    for name, add, handler, text in [
            ('sample', sample.add_arguments, sample.build, 'T1: chọn chunk hạt giống'),
            ('generate', teacher.add_generate_arguments, teacher.run_generate,
             'T2: teacher viết query (Kaggle)'),
            ('mine', mine.add_arguments, mine.build, 'T3: tìm negative khó'),
            ('judge', teacher.add_judge_arguments, teacher.run_judge,
             'T4: teacher chấm cặp (Kaggle)'),
            ('train', train.add_arguments, lambda a: train.run(train.finalise(a)),
             'T5: train student (Kaggle)')]:
        sub = commands.add_parser(name, help=text, description=text)
        add(sub)
        sub.set_defaults(handler=handler)
    args = parser.parse_args(argv)
    args.handler(args)
