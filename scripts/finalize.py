"""Block A, after crawling: audit | export a finished run."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from vibiomir.corpus.finalize import main


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
