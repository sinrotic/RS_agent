"""从部署环境生成私密 Alertmanager 通知配置；不发送消息、不输出接收地址。"""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def render(webhook):
    parsed = urlsplit(webhook)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('通知接收器必须为不含用户信息/fragment 的 HTTPS URL')
    # JSON 是合法 YAML；结构化序列化避免环境值注入配置。
    return json.dumps({'route': {'receiver': 'commerce-webhook', 'group_by': ['alertname', 'instance'], 'group_wait': '30s',
                                'group_interval': '5m', 'repeat_interval': '4h'},
                       'receivers': [{'name': 'commerce-webhook', 'webhook_configs': [{'url': webhook, 'send_resolved': True}]}]}, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, help='私密部署目录，不得位于 Git 仓库')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    for parent in (output.parent, *output.parents):
        if (parent / '.git').exists(): parser.error('通知 URL 可能含密钥，输出必须位于 Git 仓库之外')
    config = render(os.environ.get('RS_ALERT_WEBHOOK_URL', ''))
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as file: file.write(config)
    output.chmod(0o600)
    print('私密告警配置已生成；将 RS_ALERTMANAGER_CONFIG 指向该文件后重启 Alertmanager。')


if __name__ == '__main__': main()
