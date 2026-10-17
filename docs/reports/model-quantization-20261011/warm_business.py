"""首次正式完整推荐耗时有波动时，补测热运行；不改变业务输入。"""
import json
from pathlib import Path
from business import append_business

root = Path(__file__).resolve().parent
artifact = root / 'production-warm-business.json'
assert not artifact.exists()
artifact.write_text(json.dumps({'scope': 'warm_business_followup', 'model_base': 'http://127.0.0.1:18082/v1'}) + '\n')
append_business(artifact)
