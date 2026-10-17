"""记录本次通过测试的三个构建；哈希用于核对真实验收实例。"""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
data = {'unit_tests': {}, 'model_startup_tests': 19, 'diversity_golden_cases': 36}
for module in ('rs-service-agent', 'rs-service-recommend', 'rs-service-model'):
    target = PROJECT / 'java_agent' / module / 'target'
    data[module] = hashlib.sha256((target / (module + '.jar')).read_bytes()).hexdigest()
    counts = dict.fromkeys(('tests', 'failures', 'errors', 'skipped'), 0)
    for report in (target / 'surefire-reports').glob('TEST-*.xml'):
        suite = ET.parse(report).getroot()
        for key in counts: counts[key] += int(suite.attrib.get(key, 0))
    assert counts['tests'] and counts['failures'] == counts['errors'] == 0, (module, counts)
    data['unit_tests'][module] = counts
(HERE / 'build.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
print(json.dumps(data, ensure_ascii=False))
