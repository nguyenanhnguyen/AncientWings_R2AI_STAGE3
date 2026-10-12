"""Teacher and student registries, the prompts the teacher answers, and student loading.

Every listed model is open and was published before 2026-08-01. Students are at or under 15B
parameters (Qwen3-14B has 14.8B). The 14B reranker and embedding students start from the chat
model, not from a retrieval checkpoint, so they need more training data than 4B/8B to catch up.
"""
import json
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
    'má»™t cÃ¢u ngáº¯n há»i vá» triá»‡u chá»©ng cá»§a chÃ­nh mÃ¬nh',
    'cha máº¹ há»i vá» bá»‡nh cá»§a con nhá», cÃ³ nÃªu tuá»•i cá»§a bÃ©',
    'ngÆ°á»i lá»›n tuá»•i ká»ƒ bá»‡nh ná»n rá»“i há»i cÃ¡ch xá»­ lÃ½',
    'há»i vá» thuá»‘c: liá»u dÃ¹ng, tÃ¡c dá»¥ng phá»¥ hoáº·c tÆ°Æ¡ng tÃ¡c',
    'ká»ƒ má»™t Ä‘oáº¡n dÃ i nhiá»u chi tiáº¿t (thá»i gian, triá»‡u chá»©ng, Ä‘Ã£ khÃ¡m gÃ¬) rá»“i má»›i há»i',
    'há»i vá» cháº¿ Ä‘á»™ Äƒn uá»‘ng, sinh hoáº¡t hoáº·c phÃ²ng bá»‡nh',
    'há»i káº¿t quáº£ xÃ©t nghiá»‡m hoáº·c chá»‰ sá»‘ cÃ³ bÃ¬nh thÆ°á»ng khÃ´ng',
    'há»i cÃ³ nÃªn Ä‘i khÃ¡m khÃ´ng vÃ  khÃ¡m chuyÃªn khoa nÃ o',
]

GENERATE_SYSTEM = (
    'You write training data for a Vietnamese medical search engine. You receive one passage '
    'from a health website. Write ONE question that a Vietnamese patient or family member could '
    'realistically type, whose answer is contained in the passage.\n'
    'Rules:\n'
    '- The question is in natural, everyday Vietnamese, written as the patient, never quoting '
    'the passage and never mentioning "bÃ i viáº¿t", "Ä‘oáº¡n vÄƒn" or the website.\n'
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
    'BÃ© nhÃ  em 18 thÃ¡ng sá»‘t 39 Ä‘á»™ hai hÃ´m nay, uá»‘ng háº¡ sá»‘t xong láº¡i sá»‘t, cÃ³ cáº§n cho bÃ© Ä‘i viá»‡n '
    'khÃ´ng áº¡?',
    'TÃ´i 62 tuá»•i bá»‹ tiá»ƒu Ä‘Æ°á»ng type 2, gáº§n Ä‘Ã¢y hay tÃª bÃ¬ chÃ¢n vá» Ä‘Ãªm, nhÆ° váº­y cÃ³ pháº£i biáº¿n '
    'chá»©ng khÃ´ng vÃ  nÃªn lÃ m gÃ¬?',
    'uá»‘ng thuá»‘c trÃ¡nh thai kháº©n cáº¥p xong bá»‹ ra mÃ¡u cÃ³ sao khÃ´ng',
]

JUDGE_SYSTEM = ('Judge whether the Document meets the requirements based on the Query and the '
                'Instruct provided. Note that the answer can only be "yes" or "no".')
JUDGE_INSTRUCTION = ('Given a Vietnamese medical question, judge whether the document passage '
                     'contains information that answers it.')

# The Qwen3-Reranker prompt, kept here so block T does not depend on the retrieval package: the
# teacher's judge and the reranker student must be trained and scored on the very same strings.
QWEN_PREFIX = f'<|im_start|>system\n{JUDGE_SYSTEM}<|im_end|>\n<|im_start|>user\n'
QWEN_SUFFIX = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'


def qwen_pair_text(query, passage):
    return f'<Instruct>: {JUDGE_INSTRUCTION}\n<Query>: {query}\n<Document>: {passage}'


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


# --- Where a finished student is written -------------------------------------------------------

STUDENT_FILE = 'vibiomir_student.json'
