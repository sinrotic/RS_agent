"""固定商品环境下的 Skill 评测；gold 永远不进入 Agent 输入。"""

from .scoring import evaluate_turn

__all__ = ["evaluate_turn"]
