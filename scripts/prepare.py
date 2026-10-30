"""Block A2-A3 bridge: crawler output -> work/corpus/corpus.parquet."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from vibiomir.corpus.prepare import main


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
