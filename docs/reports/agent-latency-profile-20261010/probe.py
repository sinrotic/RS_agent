"""真实网关 → Agent → 推荐/模型/目录 → 持久化 → 商品详情的测量。"""
import argparse
import concurrent.futures
import json
import secrets
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path('/tmp/rs-agent-e2e-20261010-profile-1600')
BASE = 'http://127.0.0.1:18288'

def http(path, payload=None, token=None, route=None, base=BASE):
    headers = {'Content-Type': 'application/json'}
    if token: headers['Authorization'] = 'Bearer ' + token
    if route: headers['X-E2E-Route'] = route
    request = urllib.request.Request(base + path, headers=headers,
            data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode())
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'HTTP {error.code}: {error.read().decode()[:500]}') from None

def accounts():
    file = ROOT / 'accounts.json'
    if file.exists(): return json.loads(file.read_text())
    db = sqlite3.connect('file:/home/luo/RS_agent_java/data/models/multi_recall_20260913/candidates.sqlite?mode=ro&immutable=1', uri=True)
    profiles = [row[0] for row in db.execute("SELECT user FROM user_lists WHERE source='usercf_recall' LIMIT 8")]
    result = []
    for profile in profiles:
        password = secrets.token_hex(20)
        username = 'e2e_' + secrets.token_hex(8)
        auth = http('/api/auth/register', {'username': username, 'password': password,
                  'nickname': '并发验收', 'bindStrategy': 'selected', 'profileUserId': profile})
        result.append(dict(auth, username=username, password=password))
        file.write_text(json.dumps(result)); file.chmod(0o600)
        print('registered', len(result), flush=True)
    return result

def one(account, query='推荐耳机', route='fast', label='single'):
    token = account['accessToken']
    session = http('/api/sessions', {'entryScene': 'agent-e2e'}, token)['sessionId']
    payload = {'session_id': session, 'profile_user_id': account['profileUserId'],
               'user_message': query, 'limit': 5,
               'context': {'scene': 'agent_chat', 'client_turn_id': 'e2e-' + secrets.token_hex(12), 'a2ui_state': []}}
    headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token, 'X-E2E-Route': route}
    request = urllib.request.Request(BASE + '/api/agent/chat/stream', headers=headers,
                   data=json.dumps(payload, ensure_ascii=False).encode())
    start_epoch_ms = time.time() * 1000
    start = time.perf_counter()
    events = []; final = None; error = None; event_name = ''
    with urllib.request.urlopen(request, timeout=180) as response:
        for raw in response:
            line = raw.decode().strip()
            if line.startswith('event:'): event_name = line[6:].strip()
            if line.startswith('data:'):
                event = json.loads(line[5:].strip()); events.append({'event':event_name, 'data':event})
                if event_name == 'done': final = event.get('response')
                if event_name == 'error': error = event
    agent_ms = (time.perf_counter() - start) * 1000
    # 兼容 SSE 事件名称在 event: 行，而 data: 只有 payload 的格式。
    if final is None:
        final = next((e.get('data',{}).get('response') for e in reversed(events) if e.get('data',{}).get('response')), None)
    result = {'label': label, 'route': route, 'query': query, 'session_id': session,
              'start_epoch_ms': start_epoch_ms, 'agent_done_ms': round(agent_ms, 2), 'request_payload': payload, 'response': final, 'events': events, 'error': error}
    if final:
        ids = final.get('recommended_item_ids', final.get('recommendedItemIds'))
        if ids is None: ids = [item['item_id'] for item in final.get('recommended_items', [])]
        assert ids, '最终回答必须包含实际商品，不能对空商品列表计成功'
        begin = time.perf_counter()
        items = http('/api/catalog/items/batch', {'item_ids': ids}, token)
        assert {item['item_id'] for item in items} == set(ids), '目录必须补齐所有最终商品'
        result.update(catalog_ms=round((time.perf_counter()-begin)*1000, 2),
                      complete_with_catalog_ms=round((time.perf_counter()-start)*1000, 2), catalog=items)
        history = http('/api/agent/sessions/' + session + '/history', token=token, route=route)
        result['history'] = history
        card = final.get('card_set_id', final.get('cardSetId'))
        if card:
            port = 18203 if route == 'baseline' else 18213
            try: result['recommend_trace'] = http('/api/platform/recommend/' + card + '/trace', base=f'http://127.0.0.1:{port}')
            except Exception as ex: result['trace_error'] = str(ex)
    print(label, route, query, 'agent_ms=', result['agent_done_ms'],
          'complete_ms=', result.get('complete_with_catalog_ms'), 'done=', bool(final), flush=True)
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('accounts', 'sample', 'matrix', 'concurrent', 'recall'))
    parser.add_argument('--route', default='fast')
    parser.add_argument('--query', default='推荐耳机')
    parser.add_argument('--name', default='sample')
    args = parser.parse_args()
    users = accounts()
    if args.phase == 'accounts': return
    if args.phase == 'recall':
        payload = {'agent_id': 'rs_agent', 'task_id': 'e2e-'+secrets.token_hex(8), 'session_id': 'diagnostic',
                   'account_id': users[0]['accountId'], 'profile_user_id': users[0]['profileUserId'],
                   'query': args.query, 'return_count': 6, 'recall_limit': 120, 'scene': 'agent_chat'}
        start=time.perf_counter()
        result=http('/agent/recommend/semantic-recall',payload,base='http://127.0.0.1:18213')
        result={'elapsed_ms':(time.perf_counter()-start)*1000,'response':result}
    elif args.phase == 'sample': result = one(users[0], args.query, args.route, args.name)
    else:
        result = {'single': [] if args.phase == 'concurrent' else
                  [one(users[0],args.query,args.route,'single-'+str(i)) for i in range(5)]}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            result['concurrent_8'] = list(pool.map(lambda user: one(user,args.query,args.route,'concurrent-8'), users))
    file = ROOT / (args.name+'.json'); file.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print('saved', file.name, flush=True)

if __name__ == '__main__': main()
