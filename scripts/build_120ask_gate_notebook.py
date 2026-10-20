"""Build the standalone 120ask corpus-admission notebook from current source snapshots."""
import base64
import hashlib
import json
from pathlib import Path
import zlib
from build_pubmed_efetch_notebook import literals

ROOT=Path(__file__).resolve().parents[1]


def main():
    production=json.loads((ROOT/'notebooks/crawl_corpus_kaggle_hf_upload.ipynb').read_text(encoding='utf-8'))
    pack=literals(''.join(production['cells'][6]['source']))
    keys=('crawler_snapshot.py','priority_probe_snapshot.py','ask120_snapshot.py')
    files={k:pack['EMBEDDED_FILES'][k] for k in keys}
    hashes={k:pack['EMBEDDED_SHA256'][k] for k in keys}
    for name,source in (('ask120_snapshot.py','ask120.py'),('ask120_gate.py','ask120_gate.py'),
                        ('ask120_experiments.py','ask120_experiments.py'),
                        ('ask120_experiment_baseline.json','ask120_experiment_baseline.json')):
        body=(ROOT/'scripts'/source).read_bytes()
        files[name]=base64.b85encode(zlib.compress(body,9)).decode('ascii')
        hashes[name]=hashlib.sha256(body).hexdigest()
    cells=[]
    def add(kind,text):
        cell={'cell_type':kind,'id':f'ask120-gate-{len(cells)}','metadata':{},
              'source':(text.strip()+'\n').splitlines(keepends=True)}
        if kind=='code':
            compile(text,'gate_notebook_cell','exec')
            cell.update(execution_count=None,outputs=[])
        cells.append(cell)
    add('markdown','''
# 120ask — kiểm tra parser và xét nhập candidate corpus

Tên file legacy giữ “50”, LIMIT hiện là 1.000. Mặc định **replay** ZIP 1.000 URL đã có,
kiểm hash và parse lại byte HTML; không gửi request, tải Parquet/HF hoặc chạy code trong ZIP.
Gắn ZIP vào Kaggle Input và bật Run All. Đặt INPUT_RUN_ZIP rõ ràng nếu có nhiều bản;
local tự tìm đúng file trong Downloads nếu còn. Không ghi đè run đầu vào.

Ba lớp độc lập: truy cập, chất lượng parser và quyết định INCLUDE/REVIEW/EXCLUDE theo thread.
INCLUDE chỉ tạo **candidate**, không xác nhận độ đúng y khoa và không upload/publish.
Audio-only không vào corpus chữ. Trang có thể INCLUDE_PARTIAL; giữ câu hỏi, người trả lời,
reply ID và thứ tự follow-up. Document ID luôn là ID nguồn trong sample/Parquet.
''')
    add('code','''
from pathlib import Path
import sys
from datetime import datetime, timezone

MODE = 'replay'  # replay | crawl_new
INPUT_RUN_ZIP = None  # Kaggle: '/kaggle/input/.../check_120ask_20261018T022128241058Z.zip'
INPUT_RUN_DIR = None
LIMIT = 1000
SEED = 20261020
SOURCE_PARQUET = None  # crawl_new: đặt Parquet có id(int64), url(string)
HISTORY_PATHS = []     # ZIP run hoặc thư mục/file JSONL mẫu/lịch sử cũ
MANUAL_REVIEW_PATH = None
MIN_ANSWER_CHARS = 20
EXPORT_CANDIDATE_CORPUS = True
RUN_EXPERIMENTS = True  # Offline A/B; cần replay đủ regression và EXPORT_CANDIDATE_CORPUS=True.
ALLOW_UPLOAD = False
DELAY = 2.0
ATTEMPTS = 2
CONNECT_TIMEOUT = 8.0
READ_TIMEOUT = 20.0
REQUEST_BUDGET = 60.0
REQUESTS_TRUST_ENV = False
RESPECT_ROBOTS = False
STOP_ON_BLOCK = True
RESUME_OUTPUT_DIR = None  # Chỉ run mới của gate có cùng parser/policy/input; không trỏ run nguồn cũ.
WORKDIR = Path('/kaggle/working') if sys.platform.startswith('linux') and Path('/kaggle/working').is_dir() else Path.cwd()
RUN_DIR = Path(RESUME_OUTPUT_DIR) if RESUME_OUTPUT_DIR else WORKDIR/'runs'/datetime.now(timezone.utc).strftime('ask120_gate_%Y%m%dT%H%M%S%fZ')
if MODE not in ('replay','crawl_new'): raise ValueError('MODE không hợp lệ')
if ALLOW_UPLOAD: raise ValueError('Notebook này không cho upload')
if sys.version_info < (3,11): raise RuntimeError('Cần Python 3.11+')
''')
    add('code','''
# Chỉ cài package còn thiếu, không nâng cấp rộng requests/pandas.
import importlib.util
import subprocess
needed={'lxml':'lxml','pyarrow':'pyarrow','IPython':'ipython'}
if RUN_EXPERIMENTS:
    needed['requests']='requests'
if MODE=='crawl_new':
    needed.update(requests='requests',trafilatura='trafilatura',tld='tld')
missing=[package for module,package in needed.items() if importlib.util.find_spec(module) is None]
if missing:subprocess.run([sys.executable,'-m','pip','install','--quiet',*missing],check=True)
''')
    add('code', 'import base64\nimport hashlib\nimport json\nimport zlib\n\nPACK = '+repr(
        {'EMBEDDED_FILES':files,'EMBEDDED_SHA256':hashes})+'''

RUN_DIR.mkdir(parents=True,exist_ok=True)
SUPPORT_DIR=RUN_DIR/'support'
SUPPORT_DIR.mkdir(exist_ok=True)
for name,payload in PACK['EMBEDDED_FILES'].items():
    body=zlib.decompress(base64.b85decode(payload))
    if hashlib.sha256(body).hexdigest()!=PACK['EMBEDDED_SHA256'][name]:raise ValueError('Snapshot hash mismatch: '+name)
    path=SUPPORT_DIR/name
    if path.exists() and path.read_bytes()!=body:raise ValueError('Code changed; use a new RUN_DIR')
    path.write_bytes(body)
spec=importlib.util.spec_from_file_location('ask120_gate_runtime',SUPPORT_DIR/'ask120_gate.py')
gate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
POLICY={**gate.POLICY,'min_answer_chars':MIN_ANSWER_CHARS}
assert gate.sha(Path(gate.PARSER.__file__).read_bytes())==PACK['EMBEDDED_SHA256']['ask120_snapshot.py']
print('Output:',RUN_DIR)
print('Parser:',gate.PARSER.VERSION,'SHA-256:',PACK['EMBEDDED_SHA256']['ask120_snapshot.py'])
''')
    add('code','''
if MODE=='replay':
    INPUT_PATH=gate.locate_input(INPUT_RUN_ZIP,INPUT_RUN_DIR)
    if INPUT_PATH.resolve()==RUN_DIR.resolve():raise ValueError('Output phải khác run nguồn')
    print('Replay input:',INPUT_PATH)
else:
    if not SOURCE_PARQUET:raise ValueError('crawl_new cần SOURCE_PARQUET rõ ràng')
    print('Crawl mới: 1 worker; mẫu loại URL lịch sử theo question ID/canonical, không chia HTTP/HTTPS 50–50.')
    if not HISTORY_PATHS:print('Chưa có lịch sử đầy đủ: không bảo đảm toàn bộ mẫu chưa từng crawl.')
''')
    add('code','''
def build_outputs():
    return gate.build_outputs(RUN_DIR,manual_review_path=MANUAL_REVIEW_PATH,
                              export_candidates=EXPORT_CANDIDATE_CORPUS)
''')
    add('markdown','''
## Replay hoặc crawl mới

Replay đọc raw response cuối, kiểm hash, lưu raw và kết quả mới song song baseline.
Không import support/script từ input. Raw thiếu hoặc hash sai trở thành EXCLUDE có reason.
Crawl mới giới hạn một worker/delay 2 giây, dừng khi 429/challenge, không browser.
Checkpoint gắn parser/policy hash; resume không bỏ qua kết quả khác phiên bản.
Sau interrupt có thể chạy lại ô tổng hợp và ô ZIP để lưu phần hoàn tất.
''')
    add('code','''
try:
    if MODE=='replay':
        samples=gate.replay(INPUT_PATH,RUN_DIR,POLICY)
    else:
        samples=gate.crawl_new(SOURCE_PARQUET,RUN_DIR,POLICY,limit=LIMIT,seed=SEED,
            history_paths=HISTORY_PATHS,support_dir=SUPPORT_DIR,
            delay=DELAY,attempts=ATTEMPTS,timeout=(CONNECT_TIMEOUT,READ_TIMEOUT),
            budget=REQUEST_BUDGET,trust_env=REQUESTS_TRUST_ENV,respect_robots=RESPECT_ROBOTS,
            stop_on_block=STOP_ON_BLOCK)
finally:
    if (RUN_DIR/'manifest.json').exists() and (RUN_DIR/'sample.jsonl').exists():
        summary=build_outputs()
''')
    add('code','''
from IPython.display import display, FileLink
summary=build_outputs()
display(summary)
print('Kết luận:',summary['readiness'])
print('Candidate:',summary['candidate_documents'],'documents /',summary['candidate_threads'],'threads')
print('Manual review:',summary['manual_reviewed'],'/',summary['manual_required'])
print('Đọc report.md và regression_comparison.csv; không chỉ so số accepted.')
''')
    add('markdown','''
## Thí nghiệm A/B — kiểm chứng hướng sửa (20/10/2026)

Các ô dưới chạy **offline**, dùng bản sao và fixture riêng. Baseline là snapshot V3 trước fix,
được đóng băng và kiểm hash; candidate là source đã fix hiện tại, sao vào `experiments/.../suggested_patch/`. Không sửa source production
hoặc dùng nhãn thử làm review nội dung thật. Mỗi lần chạy ô khởi tạo tạo thư mục thí nghiệm mới.

Ba giả thuyết: (1) giữ nhãn PARSER_ERROR khi chọn lại mẫu review, (2) phát hiện raw/metadata
đổi trước khi resume và khôi phục raw output bị mất, (3) lưu media câu hỏi và chuyển REVIEW.
Cuối cùng parse lại toàn bộ raw bằng bản sửa thử để đo thay đổi candidate/regression.
Baseline FAIL ở các ca tái hiện lỗi là kết quả thí nghiệm; candidate phải PASS các guard đã đặt.
Đặt RUN_EXPERIMENTS=False để chỉ chạy check thường. Các thí nghiệm cần mẫu có đủ chín regression
và ít nhất 50 thread INCLUDE thông thường; không áp dụng trực tiếp cho crawl_new thiếu các ca này.
''')
    add('code','''
# Khởi tạo thí nghiệm; helper được đóng gói và kiểm hash như parser/gate.
if RUN_EXPERIMENTS:
    spec_exp=importlib.util.spec_from_file_location('ask120_experiment_runtime',SUPPORT_DIR/'ask120_experiments.py')
    experiments=importlib.util.module_from_spec(spec_exp)
    spec_exp.loader.exec_module(experiments)
    EXPERIMENT_DIR=RUN_DIR/'experiments'/datetime.now(timezone.utc).strftime('ab_%Y%m%dT%H%M%S%fZ')
    EXP=experiments.prepare(gate,RUN_DIR,EXPERIMENT_DIR)
    print('Bản sửa thử và kết quả:',EXPERIMENT_DIR)
''')
    add('code','''
# Thí nghiệm 1: nhãn EXCLUDE + PARSER_ERROR phải còn trong audit và chặn readiness.
# Nhãn giả lập có raw/parser/policy hash thật; kiểm thêm nhãn stale vẫn bị từ chối.
if RUN_EXPERIMENTS:
    manual_ab=experiments.manual_review_ab(EXP)
    display(manual_ab)
''')
    add('code','''
# Thí nghiệm 2: nguồn đổi phải từ chối resume; nguồn không đổi không parse lại.
# Kiểm riêng raw+hash, final_url, charset, HTTP status, mất raw output và hash nguồn sai.
if RUN_EXPERIMENTS:
    resume_ab=experiments.resume_ab(EXP)
    display(resume_ab)
''')
    add('code','''
# Thí nghiệm 3: text thuần, ảnh y khoa, lazy image, private placeholder và template fallback.
# Ảnh chưa rõ vai trò vẫn REVIEW; không tự đoán ảnh trang trí để cho qua gate.
if RUN_EXPERIMENTS:
    media_ab=experiments.media_ab(EXP)
    display(media_ab)
''')
    add('code','''
# Thí nghiệm 4: parse lại tất cả raw đã kiểm hash bằng parser/gate candidate.
# So candidate ID/text, quyết định trang, chín regression và các invariant văn bản.
if RUN_EXPERIMENTS:
    impact_ab=experiments.impact_replay(EXP)
    display(impact_ab)
''')
    add('code','''
# Báo cáo A/B + bản sao source hiện tại để đối chiếu với baseline V3 trước fix.
if RUN_EXPERIMENTS:
    from IPython.display import Markdown
    experiment_report=experiments.report(EXP)
    display(Markdown(experiment_report.read_text(encoding='utf-8')))
    display(FileLink(str(experiment_report)))
    display(FileLink(str(EXPERIMENT_DIR/'experiment_results.json')))
    display(FileLink(str(EXPERIMENT_DIR/'suggested.patch')))
    display(FileLink(str(EXPERIMENT_DIR/'suggested_patch/ask120_gate.py')))
    display(FileLink(str(EXPERIMENT_DIR/'suggested_patch/ask120_snapshot.py')))
''')
    add('code','''
import shutil
archive=Path(shutil.make_archive(str(RUN_DIR),'zip',root_dir=RUN_DIR))
for name in ('summary.json','report.md','regression_comparison.csv','corpus_decisions.csv',
             'manual_review_sheet.csv','corpus_candidates.jsonl','corpus_candidates.parquet'):
    display(FileLink(str(RUN_DIR/name)))
display(FileLink(str(archive)))
''')
    add('markdown','''
HTTP success không phải quyết định nhập corpus. baseline_* giữ QC/probe cũ;
parser_status/flags mới tách khỏi source_flags và corpus_decision.
qa_threads_all.jsonl giữ mọi thread; include/review/exclude là các tập riêng.
Candidate chỉ chứa thread INCLUDE, một document mỗi ID nguồn; provenance và quan hệ turn
nằm trong JSONL/sidecar, Parquet dùng adapter đúng cột production.

SHORT_MAIN_ANSWER_REVIEW không kết luận câu ngắn sai. Audio có media URL nhưng không tải/phiên âm.
Ngày là ngày hỏi. Các cờ quảng bá yêu cầu review nguồn, không sửa lời gốc.
Thiếu ngày đơn lẻ là warning. Không tự tạo nhãn con người đã review.

READY_FOR_FILTERED_PILOT chỉ có nghĩa regression và invariant tự động đạt.
Muốn READY_FOR_FILTERED_CORPUS, tải phiếu review, đối chiếu raw, ghi reviewer_decision,
reviewer_notes, reviewed_at, rồi đặt MANUAL_REVIEW_PATH và tổng hợp lại.
Phiếu chọn tối thiểu 50 thread INCLUDE có seed và phủ tuổi/độ dài/partial, cộng regression/cờ mới/nguồn.
Không suy rộng kết quả thành toàn bộ 98.160 URL. Không upload corpus.
''')
    nb={'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},
        'language_info':{'name':'python','version':'3.11'}},'nbformat':4,'nbformat_minor':5}
    (ROOT/'notebooks/check_120ask_50.ipynb').write_text(json.dumps(nb,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')


if __name__=='__main__':main()
