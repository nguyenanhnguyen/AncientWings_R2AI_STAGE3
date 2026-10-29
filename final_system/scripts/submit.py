"""Block D: build and validate submission.zip."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from vibiomir.submission.build import main


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
