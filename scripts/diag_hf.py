"""One-off: show what the current HF_TOKEN can actually see. Delete after use."""
import os

from huggingface_hub import HfApi

token = os.environ.get('HF_TOKEN')
print('HF_TOKEN env var set:', bool(token), '| length:', len(token) if token else 0)
if not token:
    raise SystemExit('HF_TOKEN chưa được set trong cửa sổ PowerShell này.')

api = HfApi(token=token)
who = api.whoami()
print('Đăng nhập với:', who['name'], '| loại token:', who.get('auth', {}).get('accessToken', {}).get('role'))

for repo_id, repo_type in [('AncientWings/AncientWings_R2AI_STAGE3_ds', 'dataset'),
                           ('AncientWings/AncientWings_R2AI_STAGE3_model', 'model')]:
    try:
        info = api.repo_info(repo_id, repo_type=repo_type)
        print(f'{repo_type} {repo_id}: THẤY ĐƯỢC, private={info.private}')
    except Exception as error:
        print(f'{repo_type} {repo_id}: LỖI -> {type(error).__name__}: {error}')
