"""Teacher and student registries, the prompts the teacher answers, and student loading.

Every listed model is open and was published before 2026-08-01. Students are at or under 15B
parameters (Qwen3-14B has 14.8B). The 14B reranker and embedding students start from the chat
model, not from a retrieval checkpoint, so they need more training data than 4B/8B to catch up.
"""
import hashlib
import json
import os
from pathlib import Path
import re

from ..common.schema import detect_language, normalise_for_match

TEACHERS = {
    # Official AWQ checkpoint; vLLM runs it with tensor parallelism over Kaggle's two T4s.
    'qwen3-32b-awq': {'hf_id': 'Qwen/Qwen3-32B-AWQ', 'backend': 'vllm', 'quantization': 'awq'},
    # Fallback when vLLM is unavailable: bitsandbytes 4-bit spread over both GPUs. Much slower.
    'qwen3-32b': {'hf_id': 'Qwen/Qwen3-32B', 'backend': 'hf', 'quantization': 'bnb4'},
    'qwen2.5-32b-instruct-awq': {'hf_id': 'Qwen/Qwen2.5-32B-Instruct-AWQ', 'backend': 'vllm',
                                 'quantization': 'awq'},
}

# '0.6b' is a smoke size: it runs the full training loop on the 4GB laptop before Kaggle hours
# are spent. The translator smoke base is the reranker checkpoint, already in the local cache.
STUDENTS = {
    'reranker': {'0.6b': 'Qwen/Qwen3-Reranker-0.6B', '4b': 'Qwen/Qwen3-Reranker-4B',
                 '8b': 'Qwen/Qwen3-Reranker-8B', '14b': 'Qwen/Qwen3-14B'},
    'embedding': {'0.6b': 'Qwen/Qwen3-Embedding-0.6B', '4b': 'Qwen/Qwen3-Embedding-4B',
                  '8b': 'Qwen/Qwen3-Embedding-8B', '14b': 'Qwen/Qwen3-14B'},
    'translator': {'0.6b': 'Qwen/Qwen3-Reranker-0.6B', '4b': 'Qwen/Qwen3-4B',
                   '8b': 'Qwen/Qwen3-8B', '14b': 'Qwen/Qwen3-14B'},
}

# Students run 4-bit unless they fit a 16GB T4 in fp16 with room for activations.
STUDENT_QUANTIZE = {'0.6b': 'none', '4b': 'none', '8b': '4bit', '14b': '4bit'}

STYLES = [
    'một câu ngắn hỏi về triệu chứng của chính mình',
    'cha mẹ hỏi về bệnh của con nhỏ, có nêu tuổi của bé',
    'người lớn tuổi kể bệnh nền rồi hỏi cách xử lý',
    'hỏi về thuốc: liều dùng, tác dụng phụ hoặc tương tác',
    'kể một đoạn dài nhiều chi tiết (thời gian, triệu chứng, đã khám gì) rồi mới hỏi',
    'hỏi về chế độ ăn uống, sinh hoạt hoặc phòng bệnh',
    'hỏi kết quả xét nghiệm hoặc chỉ số có bình thường không',
    'hỏi có nên đi khám không và khám chuyên khoa nào',
]

GENERATE_SYSTEM = (
    'You write training data for a Vietnamese medical search engine. You receive one passage '
    'from a health website. Write ONE question that a Vietnamese patient or family member could '
    'realistically type, whose answer is contained in the passage.\n'
    'Rules:\n'
    '- The question is in natural, everyday Vietnamese, written as the patient, never quoting '
    'the passage and never mentioning "bài viết", "đoạn văn" or the website.\n'
    '- Use different wording from the passage: lay terms, symptoms described in the patient\'s '
    'own words, typos are fine. Keep every fact the answer depends on.\n'
    '- "evidence" is a short span copied character for character from the passage that answers '
    'the question.\n'
    '- Also translate the question to English and to Simplified Chinese, keeping every symptom, '
    'number, unit, age and drug name.\n'
    '- If the passage has no medical information a patient would ask about (ads, navigation, '
    'author bio, news without health advice), set "usable" to false and leave the rest empty.\n'
    'Answer with JSON only: {"usable": true, "query": "...", "evidence": "...", '
    '"query_en": "...", "query_zh": "..."}')

GENERATE_EXAMPLES = [
    'Bé nhà em 18 tháng sốt 39 độ hai hôm nay, uống hạ sốt xong lại sốt, có cần cho bé đi viện '
    'không ạ?',
    'Tôi 62 tuổi bị tiểu đường type 2, gần đây hay tê bì chân về đêm, như vậy có phải biến '
    'chứng không và nên làm gì?',
    'uống thuốc tránh thai khẩn cấp xong bị ra máu có sao không',
]

JUDGE_SYSTEM = ('Judge whether the Document meets the requirements based on the Query and the '
                'Instruct provided. Note that the answer can only be "yes" or "no".')
JUDGE_INSTRUCTION = ('Given a Vietnamese medical question, judge whether the document passage '
                     'contains information that answers it.')


def generate_messages(passage, style):
    examples = '\n'.join(f'- {text}' for text in GENERATE_EXAMPLES)
    user = (f'Question style to use: {style}.\n'
            f'Examples of how patients write (style only, not topics):\n{examples}\n\n'
            f'Passage:\n{passage}')
    return [{'role': 'system', 'content': GENERATE_SYSTEM}, {'role': 'user', 'content': user}]


def judge_messages(query, passage):
    user = f'<Instruct>: {JUDGE_INSTRUCTION}\n<Query>: {query}\n<Document>: {passage}'
    return [{'role': 'system', 'content': JUDGE_SYSTEM}, {'role': 'user', 'content': user}]


_JSON_OBJECT = re.compile(r'\{.*\}', re.DOTALL)


def parse_generation(raw, passage):
    """-> (record, None) or (None, reason). The evidence must really be in the passage."""
    from ..retrieval.translate import check_translation

    text = re.sub(r'<think>.*?</think>', '', raw or '', flags=re.DOTALL).strip()
    match = _JSON_OBJECT.search(text)
    if not match:
        return None, 'no_json'
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, 'bad_json'
    if not isinstance(data, dict):
        return None, 'bad_json'
    if data.get('usable') is False:
        return None, 'not_usable'
    query = str(data.get('query') or '').strip()
    evidence = str(data.get('evidence') or '').strip()
    if len(query) < 15:
        return None, 'query_too_short'
    if detect_language(query) != 'vi':
        return None, 'query_not_vietnamese'
    folded_passage = normalise_for_match(passage)
    if not evidence or normalise_for_match(evidence) not in folded_passage:
        return None, 'evidence_not_in_passage'
    if normalise_for_match(query) in folded_passage:
        return None, 'query_copied_from_passage'
    record = {'query': query, 'evidence': evidence}
    for lang in ('en', 'zh'):
        translated = str(data.get(f'query_{lang}') or '').strip()
        # A bad translation only loses translator data; the Vietnamese query stays usable.
        record[f'query_{lang}'] = None if check_translation(query, translated, lang) else translated
    return record, None


# --- Students inside the pipeline -------------------------------------------------------------

STUDENT_FILE = 'vibiomir_student.json'


def _adapter_digest(folder):
    digest = hashlib.sha256()
    for path in sorted(Path(folder).glob('adapter_*')):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def discover_students(task, root=None):
    """{'student:<dir name>': config} for finished students of one task under VIBIOMIR_STUDENTS."""
    root = Path(root or os.environ.get('VIBIOMIR_STUDENTS', 'work/students'))
    found = {}
    if not root.is_dir():
        return found
    for marker in sorted(root.glob(f'*/{STUDENT_FILE}')):
        info = json.loads(marker.read_text(encoding='utf-8'))
        if info.get('task') != task:
            continue
        config = dict(info['config'])
        config.update(hf_id=info['base'], adapter=str(marker.parent),
                      adapter_sha=_adapter_digest(marker.parent), quantize=info['quantize'])
        found[f'student:{marker.parent.name}'] = config
    return found


def load_backbone(model_class, config, device, dtype, revision=None, **extra):
    """Base weights (optionally 4-bit) plus the student's LoRA adapter when the config has one."""
    import torch

    kwargs = dict(torch_dtype=dtype, revision=revision, **extra)
    # Prefer safetensors when available, but support official bin-only checkpoints
    # such as BAAI/bge-m3. Preserve an explicit caller format restriction.
    kwargs.setdefault('use_safetensors', config.get('use_safetensors'))
    quantized = config.get('quantize') == '4bit'
    direct = config.get('load_on_device', False) and str(device).startswith('cuda')
    if direct:
        # Load large inference checkpoints onto one GPU shard by shard, avoiding two full
        # CPU copies when both Kaggle workers load a 4B model concurrently. Requires accelerate.
        kwargs.update(device_map={'': str(device)}, low_cpu_mem_usage=True)
    if quantized:
        from transformers import BitsAndBytesConfig

        kwargs['quantization_config'] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16)
        kwargs['device_map'] = {'': str(device)}
    model = model_class.from_pretrained(config['hf_id'], **kwargs)
    if config.get('adapter'):
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, config['adapter'])
        if not quantized:
            model = model.merge_and_unload()
    if not quantized and not direct:
        model = model.to(device)
    return model.eval()
