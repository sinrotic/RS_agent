from __future__ import annotations

from rs_lab.experiments.recall.pool500.governance.fallback_completion_contract import UserSegment, classify_user_segment


def segment_for_sequence(sequence: dict[str, object], normal_threshold: int = 3) -> UserSegment:
    sequence_len = int(sequence.get("sequence_len") or len(sequence.get("recent_item_sequence", []) or []))
    positive_sequence_len = int(sequence.get("positive_sequence_len") or len(sequence.get("recent_positive_item_sequence", []) or []))
    return classify_user_segment(sequence_len=sequence_len, positive_sequence_len=positive_sequence_len, normal_threshold=normal_threshold)
