"""Block A1-A3: prepare | crawl | report | reprocess a crawl run."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from vibiomir.corpus.crawler import main


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
