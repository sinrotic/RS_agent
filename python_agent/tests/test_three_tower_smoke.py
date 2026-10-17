import importlib.util
from pathlib import Path


path = Path(__file__).parents[1] / "scripts/experiments/three_tower_smoke.py"
spec = importlib.util.spec_from_file_location("three_tower_smoke", path)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_prefixes_and_explicit_negatives_do_not_use_future_or_holdout():
    def event(item, time, rating):
        return {"user_id": "u", "parent_asin": item, "timestamp": time,
                "rating": rating, "label_binary": int(rating >= 3)}
    events = [event("a", 1, 5), event("bad", 2, 1), event("b", 3, 3),
              event("c", 4, 5), event("future_bad", 5, 1)]
    idx = {key: i for i, key in enumerate(["a", "b", "c", "bad", "future_bad"])}
    train, valid, count = smoke.make_rec_samples(events, idx)
    assert len(train) == len(valid) == 1
    assert train[0]["history"] == [idx["a"]]
    assert train[0]["target"] == idx["b"]
    assert train[0]["explicit_negatives"] == [idx["bad"]]
    assert idx["c"] not in train[0]["known_train_positives"]
    assert valid[0]["history"] == [idx["a"], idx["b"]]
    assert idx["future_bad"] not in valid[0]["explicit_negatives"]
    assert count == 1


def test_same_timestamp_is_not_history():
    rows = [{"user_id": "u", "parent_asin": key, "timestamp": t, "rating": 5, "label_binary": 1}
            for key, t in [("a", 1), ("b", 1), ("c", 2)]]
    train, valid, _ = smoke.make_rec_samples(rows, {"a": 0, "b": 1, "c": 2})
    assert train == []
    assert valid[0]["history"] == [0, 1]


def test_evidence_must_reference_real_input_quote():
    item = {"index": 1, "item_id": "B123", "title": "Bluetooth Mouse", "split": "train", "group": "g",
            "facts": [{"field": "title_clean", "text": "Bluetooth Mouse"}]}
    good = {"query": "Need a Bluetooth mouse", "language": "en",
            "evidence": [{"field": "title_clean", "quote": "Bluetooth Mouse"}]}
    bad = {**good, "evidence": [{"field": "title_clean", "quote": "waterproof"}]}
    accepted, rejected = smoke.validate_generated({"queries": [good, bad]}, item)
    assert len(accepted) == len(rejected) == 1
    assert accepted[0]["review_status"] != "human"


def test_english_text_cannot_be_marked_chinese():
    item = {"index": 1, "item_id": "B123", "title": "Bluetooth Mouse", "split": "train", "group": "g",
            "facts": [{"field": "title_clean", "text": "Bluetooth Mouse"}]}
    row = {"query": "Need a Bluetooth mouse", "language": "zh",
           "evidence": [{"field": "title_clean", "quote": "Bluetooth Mouse"}]}
    accepted, rejected = smoke.validate_generated({"queries": [row]}, item)
    assert not accepted
    assert len(rejected) == 1
