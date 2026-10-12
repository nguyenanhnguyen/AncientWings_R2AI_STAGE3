"""One entry point for every stage: python scripts/vibiomir.py <stage> [options].

    pipeline    crawl data -> submission.zip, one stage per subprocess (the usual command)
    prepare     crawl runs / parquet -> corpus.parquet
    chunk       chunk the corpus, preserving source offsets
    index       `bm25`, `dense`, `all`
    translate   query translations with the local LLM
    retrieve    retrieval + rerank -> candidates.jsonl
    submit      candidates -> validated submission.zip
    evaluate    `sheet`, `collect`, `score`, `pseudo`
    benchmark   CUDA preflight and batch throughput measurement
    teach       block T: 32B teacher -> 4B/8B/14B students

`python scripts/vibiomir.py <stage> --help` shows the options of one stage.
"""
import importlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

STAGES = {
    'pipeline': 'vibiomir.pipeline',
    'prepare': 'vibiomir.corpus.prepare',
    'chunk': 'vibiomir.corpus.chunk',
    'index': 'vibiomir.index.build',
    'translate': 'vibiomir.retrieval.translate',
    'retrieve': 'vibiomir.retrieval.run',
    'submit': 'vibiomir.submission.build',
    'evaluate': 'vibiomir.evaluation.run',
    'benchmark': 'vibiomir.benchmark',
    'teach': 'vibiomir.teach.cli',
}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if len(sys.argv) < 2 or sys.argv[1] not in STAGES:
        print(__doc__)
        raise SystemExit(0 if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help') else 2)
    stage = sys.argv.pop(1)
    sys.argv[0] = f'vibiomir.py {stage}'
    importlib.import_module(STAGES[stage]).main()


if __name__ == '__main__':
    main()
