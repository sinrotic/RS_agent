"""从既有无参数计时探针提取匿名方法耗时；不发布业务日志或异常原文。"""
import collections
import json
import re
import subprocess

from deploy_live import ROOT, NAME


def main():
    deployment = json.loads((ROOT / 'deployment.json').read_text())
    result = subprocess.run(['docker', 'logs', '--since', str(deployment['switched_at_epoch']), NAME],
                            capture_output=True, text=True)
    rows = []
    exception_types = collections.Counter()
    classifications = collections.Counter()
    for line in (result.stdout + result.stderr).splitlines():
        if line.startswith('RS_PROFILE '):
            try:
                trace = json.loads(line[len('RS_PROFILE '):])
            except json.JSONDecodeError:
                continue
            nodes = trace['nodes']
            if nodes[0]['method'] not in ('InMemoryAgentOrchestrationService.streamChat', 'InMemoryAgentOrchestrationService.chat'):
                continue
            model = []
            for index, node in enumerate(nodes):
                if node['method'] != 'SpringAiAgentModelStreamClient.streamAssistantEvents':
                    continue
                parent = node['parent']
                nested = False
                while parent >= 0:
                    if nodes[parent]['method'] == node['method']:
                        nested = True
                        break
                    parent = nodes[parent]['parent']
                if not nested:
                    model.append(node)
            total = nodes[0]['duration_ns'] / 1e6
            model_ms = sum(node['duration_ns'] / 1e6 for node in model)
            rows.append({'epoch_ms': trace['epoch_ms'], 'total_ms': round(total, 3),
                'model_stream_calls': len(model), 'model_stream_ms': round(model_ms, 3),
                'model_fraction': round(model_ms / total, 6) if total else 0,
                'root_failed': nodes[0]['failed'],
                'failed_methods': list(dict.fromkeys(node['method'] for node in nodes if node.get('failed')))} )
        elif re.match(r'^\s*(?:Caused by: )?[\w.$]+(?:Exception|Error)(?::|$)', line):
            match = re.search(r'([\w.$]+(?:Exception|Error))', line)
            if match:
                exception_types[match.group(1)] += 1
            if 'timeout' in line.lower() or 'timed out' in line.lower():
                classifications['exception_mentions_timeout'] += 1
            if 'socket closed' in line.lower():
                classifications['exception_mentions_socket_closed'] += 1
    inspection = json.loads(subprocess.check_output(['docker', 'inspect', NAME], text=True))[0]
    env = dict(value.split('=', 1) for value in inspection['Config']['Env'] if '=' in value)
    report = {'agent_traces': rows, 'exception_type_counts': dict(exception_types),
              'exception_classifications': dict(classifications),
              'java_timing_agent_enabled': '-javaagent:' in env.get('JAVA_OPTS', ''),
              'scope': '共享时间窗口异常类型；没有匿名调用树时不得推导纯模型耗时占比'}
    (ROOT / 'profile-summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print('匿名 Agent 计时轨迹', len(rows), '异常类型', dict(exception_types), flush=True)


if __name__ == '__main__':
    main()
