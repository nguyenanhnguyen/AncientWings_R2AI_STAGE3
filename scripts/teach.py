"""Block T: teacher data and student training."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from vibiomir.teach.cli import main


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
