"""复用冻结规划输入，保持私有请求在原服务器受限目录。"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, '/tmp/rs-agent-partial-quantization-20261011')
import tool_replay

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--port', type=int, choices=[18082, 18092], required=True)
    args = parser.parse_args()
    records = tool_replay.dataset()
    tool_replay.dataset = lambda: records
    tool_replay.ROOT = ROOT
    tool_replay.run(args.label, args.port)
