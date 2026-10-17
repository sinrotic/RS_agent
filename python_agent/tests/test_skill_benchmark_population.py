"""评测构建 Interface：全量过去统计与受限画像快照不得混淆。"""

import json

from rs_core.offline.evaluation.skill_benchmark.population import prepare_population
from rs_core.offline.evaluation.skill_benchmark.personalized import build_personalized_benchmark


def test_population_uses_full_past_counts_and_conditions_quantiles_on_history_capability(tmp_path):
    history = []
    for user in range(10):
        for index in range(user + 1):
            history.append(
                {
                    "user_id": f"u{user}",
                    "parent_asin": f"p{index}",
                    "timestamp": 100 + index,
                    "rating": 5,
                }
            )
    targets = [
        {"user_id": f"u{user}", "parent_asin": "p1", "timestamp": 200, "rating": 5}
        for user in range(10)
    ]
    paths = []
    for name, rows in (("history", history), ("target", targets)):
        path = tmp_path / f"{name}.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        paths.append(path)
    result = prepare_population(
        paths[0], [paths[1]], tmp_path / "population", candidate_user_limit=2
    )
    # 具备 >=5 正向历史的用户频次 [5,6,7,8,9,10]，商品频次 [5,6,7,8,9,10]。
    assert result["user_count_bounds"] == [8, 9]
    assert result["item_count_bounds"] == [8, 9]
    assert result["past_users"] == 10 and result["past_items"] == 10
    assert result["eligible_user_population"] == 6
    assert result["eligible_item_population"] == 6
    assert result["user_counts"] == {"u7": 8, "u8": 9}
    assert result["item_counts"]["p1"] == 9
    assert result["sources"]["history"]["rows"] == 55
    assert result["sources"]["history"]["complete"] is True
    snapshot = [
        json.loads(line)
        for line in (tmp_path / "population/history.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(snapshot) == 17
    assert all(row["timestamp"] < 200 for row in snapshot)
    assert result["content_sha256"]


def test_benchmark_does_not_recompute_popularity_from_sampled_profile_snapshot(tmp_path):
    history, targets, metadata = [], [], []
    for user in range(10):
        for position in range(user + 1):
            item = f"p-{user}-{position}"
            history.append(
                {
                    "user_id": f"u{user}",
                    "parent_asin": item,
                    "timestamp": 100 + position,
                    "rating": 5,
                }
            )
            history.extend(
                {
                    "user_id": f"background-{item}-{j}",
                    "parent_asin": item,
                    "timestamp": 50,
                    "rating": 5,
                }
                for j in range(9)
            )
            metadata.append(
                {
                    "parent_asin": item,
                    "title": item,
                    "price": 10 + position,
                    "categories": ["Electronics", "headphones" if position == 0 else "clips"],
                    "store": f"store-{user}",
                }
            )
        targets.append(
            {
                "user_id": f"u{user}",
                "parent_asin": f"p-{(user + 1) % 10}-0",
                "timestamp": 200,
                "rating": 5,
            }
        )
    paths = []
    for name, rows in (("history", history), ("targets", targets), ("metadata", metadata)):
        path = tmp_path / f"{name}.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        paths.append(path)
    population = prepare_population(
        paths[0], [paths[1]], tmp_path / "population", candidate_user_limit=2
    )
    benchmark = build_personalized_benchmark(
        [paths[2]],
        population["snapshots"]["history"]["path"],
        [population["snapshots"]["targets"]["path"]],
        family_limit=2,
        catalog_limit=30,
        population_snapshot=population,
    )
    assert benchmark["manifest"]["sampling"]["past_users"] == 505
    assert benchmark["manifest"]["sampling"]["item_count_bounds"] == [10, 10]
    assert all(item["historical_interaction_count"] == 10 for item in benchmark["catalog"])
    assert benchmark["manifest"]["population_sha256"] == population["content_sha256"]
