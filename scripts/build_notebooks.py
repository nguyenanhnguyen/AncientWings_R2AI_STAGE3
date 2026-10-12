"""Embed this repository's code into notebooks/teach_kaggle.ipynb, so Kaggle runs the laptop code.

src/ and scripts/vibiomir.py are zipped (fixed timestamps: same code, same bytes) and
base64-embedded in one cell, replacing only that cell. After any code change: rerun this script and
upload the notebook again.

    python scripts/build_notebooks.py
"""
import base64
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TEACH_NOTEBOOK = ROOT / 'notebooks' / 'teach_kaggle.ipynb'
CODE_MARKER = '# Sinh tự động bởi scripts/build_notebooks.py: code của repo, nhúng trong notebook.'
# Cells written by the builders this file replaced are recognised, so an older notebook is updated
# in place instead of gaining a second code cell.
OLD_MARKERS = ('# Sinh tự động bởi scripts/build_kaggle_notebook.py',
               '# Sinh tự động bởi scripts/build_teach_notebook.py')


def build_zip():
    files = sorted(p for p in (ROOT / 'src').rglob('*.py') if '__pycache__' not in p.parts)
    files.append(ROOT / 'scripts' / 'vibiomir.py')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            # Fixed timestamp: the same code always yields the same bytes and hash.
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return buffer.getvalue(), len(files)


def code_cell(data, code_dir):
    encoded = base64.b64encode(data).decode('ascii')
    lines = [encoded[i:i + 120] for i in range(0, len(encoded), 120)]
    return (CODE_MARKER + '\n'
            '# Không sửa tay ô này; sửa code trong repo rồi chạy lại script đó.\n'
            'import base64, hashlib, io, shutil, zipfile\n'
            'from pathlib import Path\n'
            f"CODE_SHA256 = '{hashlib.sha256(data).hexdigest()}'\n"
            'CODE_ZIP = (\n' + ''.join(f"    '{line}'\n" for line in lines) + ')\n'
            'payload = base64.b64decode(CODE_ZIP)\n'
            'if hashlib.sha256(payload).hexdigest() != CODE_SHA256:\n'
            "    raise ValueError('Code nhúng bị hỏng; build lại notebook.')\n"
            f'CODE_DIR = {code_dir}\n'
            'shutil.rmtree(CODE_DIR, ignore_errors=True)\n'
            'zipfile.ZipFile(io.BytesIO(payload)).extractall(CODE_DIR)\n'
            "print('Code:', CODE_SHA256[:12], sum(1 for _ in CODE_DIR.rglob('*.py')), 'file .py')\n")


def main():
    notebook = json.loads(TEACH_NOTEBOOK.read_text(encoding='utf-8'))
    data, count = build_zip()
    new = {'cell_type': 'code', 'execution_count': None, 'metadata': {}, 'outputs': [],
           'source': code_cell(data, "Path('/kaggle/working/vibiomir/code')").splitlines(keepends=True)}
    cells = notebook['cells']
    found = [i for i, c in enumerate(cells)
             if ''.join(c['source']).startswith((CODE_MARKER,) + OLD_MARKERS)]
    if found:
        cells[found[0]] = new
    else:
        # Right after the install cell (the one that reads the HF_TOKEN secret).
        install = next(i for i, c in enumerate(cells) if 'get_secret' in ''.join(c['source']))
        cells.insert(install + 1, new)
    TEACH_NOTEBOOK.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n',
                              encoding='utf-8')
    print(f'{TEACH_NOTEBOOK.relative_to(ROOT)}: {count} file code, {len(data) / 1024:.0f} KB nén, '
          f'sha256 {hashlib.sha256(data).hexdigest()[:12]}')


if __name__ == '__main__':
    main()
