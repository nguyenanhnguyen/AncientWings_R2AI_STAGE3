"""One entry point for every stage: python scripts/vibiomir.py <stage> [options].

    pipeline    whole cascade, crawl data -> submission.zip (the usual command)
    experiments controlled ablations on a completed pipeline snapshot
    rebuild     full-corpus indexes and progressive retrieval/model experiments
    ann         build an approximate vector index from existing embeddings
    fetch       download the team corpus + BTC query/links from Hugging Face (Kaggle)
    prepare     crawl runs / parquet -> corpus.parquet
    cards       `build` document cards, `subset` chunk candidate documents
    chunk       chunk the selected corpus, preserving source offsets
    index       `bm25`, `dense`, `dense-merge`, `all`
    translate   query translations (and optional HyDE) with the local LLM
    retrieve    retrieval + rerank -> candidates.jsonl
    submit      candidates -> validated submission.zip
    evaluate    `sheet`, `collect`, `score`, `calibrate`, `pseudo`
    benchmark   CUDA preflight and batch throughput measurement
    teach       block T (teacher -> student), paused

`python scripts/vibiomir.py <stage> --help` shows the options of one stage.
"""
import importlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

STAGES = {
    'passages': 'vibiomir.retrieval.passages',
    'ann': 'vibiomir.index.ann',
    'rebuild': 'vibiomir.rebuild',
    'experiments': 'vibiomir.experiments',
    'pipeline': 'vibiomir.pipeline',
    'fetch': 'vibiomir.corpus.fetch',
    'prepare': 'vibiomir.corpus.prepare',
    'cards': 'vibiomir.corpus.cards',
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
