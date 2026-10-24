"""Refresh storage/export code without rebuilding parsers or changing user settings."""
import base64
import hashlib
import json
from pathlib import Path
import zlib

from build_pubmed_efetch_notebook import literals, replace_literals

ROOT = Path(__file__).resolve().parents[1]


def upgrade_core(body):
    source = body.decode('utf-8')
    marker = "    atomic_bytes(path, ''.join(json.dumps(r, ensure_ascii=False) + '\\n' for r in rows).encode('utf-8'))"
    if '# compact storage reports' not in source:
        replacement = '''    # compact storage reports: retain text once, in the accepted export input.
    import importlib.util
    storage_path = Path(__file__).with_name('storage_snapshot.py')
    if storage_path.exists():
        spec = importlib.util.spec_from_file_location('report_storage', storage_path)
        storage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(storage)
        return storage.write_jsonl(path, rows)
'''
        if marker not in source: raise ValueError('Unknown core JSONL implementation')
        source = source.replace(marker, replacement + marker, 1)
    return source.encode('utf-8')


def main():
    for filename in ('crawl_corpus_kaggle_hf_upload.ipynb', 'crawl_domain_samples.ipynb'):
        path = ROOT / 'notebooks' / filename
        nb = json.loads(path.read_text(encoding='utf-8'))
        for index, cell in enumerate(nb['cells']):
            text = ''.join(cell['source'])
            if cell['cell_type'] != 'code':
                if filename == 'crawl_corpus_kaggle_hf_upload.ipynb':
                    if index == 13:
                        text = '''## 7. Báo cáo, kiểm tra và xuất corpus

Ưu tiên `corpus.parquet` nén Zstandard; mặc định không tạo bản JSONL trùng.
Audit kiểm tra ID/URL và hash raw/text trước khi xuất corpus hoàn tất.
Nếu còn pending, xuất `corpus.partial.parquet` từ phần accepted đã xử lý;
đây là bản tạm chưa qua audit toàn run và chưa được upload như corpus hoàn tất.
Accepted là QC tự động, vẫn cần review nội dung.
'''
                    if index == 17:
                        text = '''## 9. Đóng gói kết quả để tải về

Hai output ưu tiên là `corpus.parquet` và `<run>_diagnostics.zip`.
ZIP kết quả của run hoàn tất chỉ chứa corpus/báo cáo, không chứa toàn bộ raw/records.
Nếu không đủ dung lượng dự phòng, bỏ qua ZIP phụ và giữ hai output riêng.
Run lỗi/chưa hoàn tất chỉ tạo ZIP resume đầy đủ khi đủ chỗ; nếu thiếu chỗ,
giữ raw/records trong thư mục run và dùng checkpoint đã upload lên HF để khôi phục.
Không dùng ZIP kết quả gọn để resume: giữ thư mục run đầy đủ hoặc checkpoint HF.

Chẩn đoán: giải nén ZIP và mở `overview.html` để xem HTTP, QC, tiến độ, CSV và log.
Để dùng runtime mới với run cũ, đặt `RECOVERY_RUN_PATH` và `RUN_TAG` mới.
Để chỉ cứu/export run cũ, đặt `POSTPROCESS_ONLY=True` và `RESUME_RUN_PATH`.
'''
                    if index == 19:
                        text = text.replace('# Cùng corpus, định dạng JSONL', '# Tùy chọn: chạy exporter --jsonl rồi bật HF_UPLOAD_JSONL')
                        text = text.replace('Mục 9 vẫn tạo ZIP đầy đủ trong Kaggle Output để tải về/resume; chỉ bật upload archive khi chủ động cần.',
                                            'Mục 9 tạo ZIP kết quả gọn nếu đủ chỗ; ZIP này không dùng để resume. Mặc định HF_UPLOAD_JSONL=False.')
                cell['source'] = text.splitlines(keepends=True)
                continue
            if 'EMBEDDED_FILES =' in text:
                values = literals(text)
                files, hashes = values['EMBEDDED_FILES'], values['EMBEDDED_SHA256']
                updates = {'storage_snapshot.py': (ROOT/'scripts/corpus_storage.py').read_bytes()}
                for name, script in (('checkpoint_snapshot.py', 'corpus_checkpoint.py'),
                                     ('pubmed_resume_snapshot.py', 'pubmed_resume.py'),
                                     ('postprocess_snapshot.py', 'notebook_postprocess.py'),
                                     ('corpus_runner_snapshot.py', 'corpus_runner.py'),
                                     ('export_snapshot.py', 'corpus_export.py')):
                    if name in files: updates[name] = (ROOT/'scripts'/script).read_bytes()
                updates['crawler_snapshot.py'] = upgrade_core(zlib.decompress(base64.b85decode(files['crawler_snapshot.py'])))
                for name, body in updates.items():
                    compile(body, name, 'exec')
                    files[name] = base64.b85encode(zlib.compress(body, 9)).decode('ascii')
                    hashes[name] = hashlib.sha256(body).hexdigest()
                text = replace_literals(text, {'EMBEDDED_FILES': files, 'EMBEDDED_SHA256': hashes})
                text = text.replace('POSTPROCESS_FILES = {', "POSTPROCESS_FILES = {'storage_snapshot.py', ") if "POSTPROCESS_FILES = {'storage_snapshot.py'" not in text else text
                text = text.replace("print('ZIP checkpoint đầy đủ:', archive, flush=True)", "print('ZIP kết quả/checkpoint (có thể bỏ qua nếu thiếu dung lượng):', archive, flush=True)")
            text = text.replace('HF_UPLOAD_JSONL = True', 'HF_UPLOAD_JSONL = False')
            text = text.replace('script in (CRAWLER, CORPUS_RUNNER) else',
                                "(script in (CRAWLER, CORPUS_RUNNER) or Path(script).name == 'storage_snapshot.py') else")
            text = text.replace("    display(FileLink(str(Path(archive).relative_to(WORKDIR))))", "    if archive is not None:\n        display(FileLink(str(Path(archive).relative_to(WORKDIR))))") if 'if archive is not None:' not in text else text
            text = text.replace("        display(FileLink(str((RUN_DIR / 'corpus.jsonl').relative_to(WORKDIR))))", "        if (RUN_DIR / 'corpus.jsonl').exists():\n            display(FileLink(str((RUN_DIR / 'corpus.jsonl').relative_to(WORKDIR))))") if "if (RUN_DIR / 'corpus.jsonl').exists():" not in text else text
            compile(text, filename, 'exec')
            cell['source'] = text.splitlines(keepends=True)
        path.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
