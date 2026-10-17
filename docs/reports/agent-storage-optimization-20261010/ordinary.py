"""真实模型普通推荐与连续三轮会话；失败原样保留，不以快速路径替代验收。"""
import json
import sys
from probe import ROOT, accounts, one
from measure import ready

ready()
users = accounts()
name = sys.argv[1] if len(sys.argv) > 1 else 'ordinary'
result = {'single': [], 'multi_turn': [], 'failures': []}
def save(): (ROOT / (name + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
def collect(group, user, query, label, session=None):
    try:
        row = one(user, query, 'fast', label, session)
    except Exception as error:
        row = {'query': query, 'label': label, 'error': str(error)}
    result[group if row.get('response') else 'failures'].append(row)
    save()
    return row

for i, query in enumerate(('推荐一款适合办公的鼠标，最好静音，说明理由',
                           '推荐适合编程使用的键盘，说明各自的区别')):
    collect('single', users[0], query, 'ordinary-' + str(i))
session = None
for i, query in enumerate(('请帮我推荐鼠标', '换一批鼠标，适合办公使用', '再推荐五款鼠标，说明理由')):
    row = collect('multi_turn', users[1], query, 'multi-turn-' + str(i), session)
    session = row.get('session_id', session)
print('普通与多轮完成，失败数', len(result['failures']), flush=True)
