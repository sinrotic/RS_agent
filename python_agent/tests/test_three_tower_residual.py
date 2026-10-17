import importlib.util
from pathlib import Path

import pytest
import torch
import torch.nn.functional as F

spec = importlib.util.spec_from_file_location("residual", Path(__file__).parents[1] / "scripts/experiments/three_tower_residual.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_initialization_preserves_item_query_and_masked_history():
    torch.manual_seed(42)
    model = module.ResidualTowers(16, 8, 5, 4)
    x = F.normalize(torch.randn(5, 16), dim=-1)
    v = model.encode_items(x, torch.arange(5))
    assert torch.allclose(v, x, atol=1e-6)
    assert torch.allclose(model.encode_query(x), x, atol=1e-6)
    history = v[torch.tensor([[0, 1, 4], [2, 3, 4]])]
    mask = torch.tensor([[1., 1., 0.], [1., 1., 1.]])
    expected = F.normalize(torch.stack([x[:2].mean(0), x[2:].mean(0)]), dim=-1)
    assert torch.allclose(model.encode_user(history, mask), expected, atol=1e-6)


def test_history_path_trains_item_and_user_but_not_query():
    model = module.ResidualTowers(16, 8)
    x = F.normalize(torch.randn(3, 16), dim=-1)
    history = model.encode_items(x[:2]).unsqueeze(0)
    u = model.encode_user(history, torch.ones(1, 2))
    # 候选是常量，Item 的梯度只能来自历史路径。
    loss = -(u * x[2]).sum()
    loss.backward()
    assert model.item.layers[-1].weight.grad.abs().sum() > 0
    assert model.user.layers[-1].weight.grad.abs().sum() > 0
    assert all(p.grad is None for p in model.query.parameters())


def test_semantic_loss_updates_query_and_item_but_not_user():
    torch.manual_seed(7)
    model = module.ResidualTowers(16, 8)
    queries = F.normalize(torch.randn(2, 16), dim=-1)
    items = F.normalize(torch.randn(4, 16), dim=-1)
    logits = model.encode_query(queries) @ model.encode_items(items).T
    F.cross_entropy(logits, torch.tensor([0, 1])).backward()
    assert model.query.layers[-1].weight.grad.abs().sum() > 0
    assert model.item.layers[-1].weight.grad.abs().sum() > 0
    assert all(p.grad is None for p in model.user.parameters())


def test_oov_zeroes_id_branch_and_cached_export_agrees():
    model = module.ResidualTowers(16, 8, 3, 4)
    with torch.no_grad():
        model.id_projection.weight.normal_()
        model.item.layers[-1].weight.normal_(std=.01)
    x = F.normalize(torch.randn(3, 16), dim=-1)
    oov = model.encode_items(x, torch.full((3,), -1))
    expected = F.normalize(x + model.item(x), dim=-1)
    assert torch.allclose(oov, expected)
    cached = model.encode_items(x, torch.arange(3)).detach()
    restored = module.ResidualTowers(16, 8, 3, 4)
    restored.load_state_dict(model.state_dict())
    actual = restored.encode_items(x, torch.arange(3))
    mask = torch.ones(1, 3)
    assert torch.allclose(restored.encode_user(actual[None], mask), model.encode_user(cached[None], mask))


def test_empty_history_rejected_and_weak_negatives_block_known_positives():
    import random
    model = module.ResidualTowers(16, 8)
    with pytest.raises(ValueError, match="empty history"):
        model.encode_user(torch.zeros(1, 2, 16), torch.zeros(1, 2))
    candidates = module.negatives(random.Random(1), 0, [0, 1, 2], 4, 10, [1, 3, 3])
    assert candidates[0] == 0
    assert len(set(candidates)) == 5
    assert not set(candidates[1:]) & {0, 1, 2}


def test_uncovered_target_counts_as_miss_and_zero_reciprocal_rank():
    result = module.metrics([1, 0, 200])
    assert result["count"] == 3
    assert result["hit@100"] == pytest.approx(1 / 3)
    assert result["target_coverage"] == pytest.approx(2 / 3)
    assert result["mrr"] == pytest.approx((1 + 1 / 200) / 3)


def test_recency_weights_use_only_history_time_and_preserve_padding():
    batch = [{"history": [0, 1], "history_ts": [0, 86400000]},
             {"history": [2], "history_ts": [86400000]}]
    _, weights = module.history_tensor(batch, "cpu", 1.)
    assert torch.allclose(weights, torch.tensor([[.5, 1.], [1., 0.]]))


def test_pilot_selection_uses_train_only_and_missing_target_stays_in_denominator(tmp_path):
    import json
    import subprocess
    import sys
    source = tmp_path / "source"
    source.mkdir()
    def write(name, data):
        (source / name).write_text("".join(json.dumps(r) + "\n" for r in data))
    manifest = {"window_policy": {"splits": {"train": {"end_ms": 10}, "valid": {"end_ms": 20}}}}
    (source / "manifest.json").write_text(json.dumps(manifest))
    write("user_sequences.train.jsonl", [{"user_id": "u", "recent_positive_item_sequence": ["a", "b", "c"], "recent_positive_timestamp_sequence": [1, 2, 3]}])
    write("canonical_items.jsonl", [{"parent_asin": iid, "title_clean": iid} for iid in ["a", "b", "c", "d"]])
    write("canonical_interactions.valid.jsonl", [{"user_id": "u", "parent_asin": "missing", "timestamp": 11, "label_binary": 1}])
    output = tmp_path / "output"
    script = Path(__file__).parents[1] / "scripts/experiments/prepare_product_pilot.py"
    subprocess.run([sys.executable, str(script), "--data", str(source), "--output", str(output), "--users", "1", "--extra-items", "1"], check=True, capture_output=True)
    valid = module.rows(output / "rec_valid.jsonl")
    assert len(valid) == 1 and valid[0]["target"] == -1
    train = module.rows(output / "rec_train.jsonl")
    assert len(train) == 2
    assert all(max(r["history_ts"]) < r["target_ts"] < 10 for r in train)
    assert valid[0]["history_ts"] == [1, 2, 3]


@pytest.mark.parametrize("mode", ["rec", "joint"])
@pytest.mark.parametrize("semantic_every", [1, 2])
def test_training_cli_writes_reproducible_results_and_respects_query_updates(tmp_path, mode, semantic_every):
    import json
    import subprocess
    import sys
    import numpy as np
    data = tmp_path / "data"
    data.mkdir()
    rng = np.random.default_rng(42)
    features = rng.normal(size=(50, 16)).astype("float32")
    features /= np.linalg.norm(features, axis=1, keepdims=True)
    np.save(data / "item_features.npy", features)
    np.save(data / "query_features.npy", features[40:46])
    sample = {"user_hash": "u", "history": [0, 1], "target": 2, "known_train_positives": [0, 1, 2], "explicit_negatives": []}
    (data / "rec_train.jsonl").write_text(json.dumps(sample) + "\n")
    (data / "rec_valid.jsonl").write_text(json.dumps({**sample, "target": 3}) + "\n")
    semantic = [{"query": f"fixture demand {i}", "item_index": 40 + i, "split": "train" if i < 4 else "valid"} for i in range(6)]
    (data / "semantic_clean.jsonl").write_text("".join(json.dumps(r) + "\n" for r in semantic))
    out = tmp_path / "run"
    subprocess.run([sys.executable, str(Path(module.__file__)), "--data", str(data), "--output", str(out), "--device", "cpu", "--mode", mode, "--semantic-eval", "--steps", "1", "--eval-every", "1", "--batch-size", "2", "--hidden", "8", "--query-lr", "2e-6", "--semantic-every", str(semantic_every)], check=True, capture_output=True)
    result = json.loads((out / "results.json").read_text())
    assert result["initial"]["max_score_error_vs_bge"] < 2e-6
    assert "semantic_clean.jsonl" in result["input_sha256"]
    checkpoint = torch.load(out / "step_1.pt", weights_only=True)
    changed_query = bool(checkpoint["model"]["query.layers.2.weight"].abs().sum() > 0)
    assert changed_query == (mode == "joint" and semantic_every == 1)
    assert result["checkpoints"][0]["semantic_updates"] == int(mode == "joint" and semantic_every == 1)
    assert (out / "training_source.py").exists()
