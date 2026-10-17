"""画像绑定的评测，在已确认的构建、工具环境与运行 Interface 验收。"""

import json
import os
import pytest

from rs_core.offline.evaluation.skill_benchmark.personalized import build_personalized_benchmark
from rs_core.offline.evaluation.skill_benchmark.environment import FixtureEnvironment
from rs_core.offline.evaluation.skill_benchmark.scoring import evaluate_turn
from rs_core.offline.evaluation.skill_benchmark.dataset import fingerprint, validate_benchmark
from rs_core.offline.evaluation.skill_benchmark.runner import run_benchmark


def test_sampling_binds_real_users_using_only_past_interactions(tmp_path):
    history, targets, metadata = [], [], []
    for user in range(10):
        for position in range(user + 1):
            item = f"p-{user}-{position}"
            history.append(
                {
                    "user_id": f"u-{user}",
                    "parent_asin": item,
                    "timestamp": 100 + position,
                    "rating": 5,
                }
            )
            metadata.append(
                {
                    "parent_asin": item,
                    "title": item,
                    "categories": ["Electronics", "headphones" if position == 0 else "clips"],
                    "price": 10 + position,
                    "store": f"store-{user}",
                }
            )
        targets.append(
            {
                "user_id": f"u-{user}",
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
    benchmark = build_personalized_benchmark(
        [paths[2]], paths[0], [paths[1]], family_limit=2, catalog_limit=30, seed=42
    )
    repeated = build_personalized_benchmark(
        [paths[2]], paths[0], [paths[1]], family_limit=2, catalog_limit=30, seed=42
    )
    assert benchmark == repeated
    assert benchmark["manifest"]["sampling"]["user_count_bounds"] == [6, 9]
    assert benchmark["manifest"]["sampling"]["item_count_bounds"] == [1, 1]
    assert len(benchmark["profiles"]) == 2
    assert benchmark["manifest"]["profile_diagnostics"]["observable_families"] == 2
    changed_seed = build_personalized_benchmark(
        [paths[2]], paths[0], [paths[1]], family_limit=2, catalog_limit=30, seed=43
    )
    assert [task["profile_user_id"] for task in benchmark["tasks"]] != [
        task["profile_user_id"] for task in changed_seed["tasks"]
    ]
    for task in benchmark["tasks"]:
        profile = benchmark["profiles"][task["profile_user_id"]]
        assert profile["profile_user_id"] in {"u-5", "u-6", "u-7", "u-8"}
        assert 6 <= profile["activity_count"] <= 9
        assert task["anchor_item_id"] not in profile["seen_item_ids"]
        assert all(event["timestamp"] < 200 for event in profile["history"])
        assert task["anchor_evidence"]["timestamp"] == 200
        assert task["anchor_evidence"]["user_id"] == task["profile_user_id"]


def test_bound_profile_changes_recommendations_and_cannot_be_switched_by_tool_arguments():
    catalog = [
        {"item_id": "A", "store": "Blue", "price": 9},
        {"item_id": "B", "store": "Red", "price": 10},
    ]
    for user, store, expected in (
        ("real-blue", "Blue", ["A", "B"]),
        ("real-red", "Red", ["B", "A"]),
    ):
        profile = {
            "profile_user_id": user,
            "seen_item_ids": [],
            "history": [],
            "profile_preferences": {"preferred_store": store},
        }
        with FixtureEnvironment(catalog, {"profile": profile}) as environment:
            memory = environment.call("session_memory", {})
            assert memory["profile_user_id"] == user
            answer = environment.call("recommend_profile_pipeline", {"return_count": 2})
            assert [item["item_id"] for item in answer["items"]] == expected
            foreign = environment.call("recommend_profile_pipeline", {"user_id": "someone-else"})
            assert foreign == {"status": "FAILED", "error": "PROFILE_USER_MISMATCH"}
            cold = environment.call("recommend_cold_fallback", {"return_count": 2})
            assert [item["item_id"] for item in cold["items"]] == ["A", "B"]


def test_history_frequency_utility_uses_independent_literal_expected_score():
    catalog = [
        {"item_id": "A", "category": "pens", "store": "Blue"},
        {"item_id": "B", "category": "clips", "store": "Red"},
    ]
    gold = {
        "k": 2,
        "hard": [{"field": "category", "op": "in", "value": ["pens", "clips"]}],
        "soft": [
            {
                "field": "category",
                "op": "lookup",
                "scores": {"pens": 1, "clips": 0.5},
                "weight": 0.7,
            },
            {"field": "store", "op": "lookup", "scores": {"Blue": 1}, "weight": 0.3},
        ],
    }
    result = evaluate_turn(catalog, gold, {"item_ids": ["B", "A"], "outcome": "recommend"})
    # 理想相关度 [1, .35]，反序 DCG=.35+1/log2(3)。
    assert result["task_score"] == pytest.approx(80.34971606286726)


def test_runner_delivers_bound_profile_to_real_fixture_without_target_or_gold():
    from urllib.request import Request, urlopen

    catalog = [
        {"item_id": "A", "category": "pens", "price": 10, "store": "Blue"},
        {"item_id": "B", "category": "pens", "price": 12, "store": "Blue"},
    ]
    profile = {
        "profile_user_id": "dataset-user",
        "history_cutoff_exclusive": 200,
        "activity_count": 3,
        "history": [],
        "seen_item_ids": ["past"],
        "profile_preferences": {"preferred_store": "Blue"},
    }
    profiles = {"dataset-user": profile}
    benchmark = {
        "schema_version": "rs-skill-benchmark/1",
        "catalog": catalog,
        "profiles": profiles,
        "environment": {},
        "manifest": {
            "catalog_sha256": fingerprint(catalog),
            "profiles_sha256": fingerprint(profiles),
            "human_reviewed": False,
        },
        "tasks": [
            {
                "task_id": "t",
                "family_id": "f",
                "kind": "personalized",
                "split": "test",
                "profile_user_id": "dataset-user",
                "anchor_item_id": "A",
                "anchor_evidence": {
                    "user_id": "dataset-user",
                    "parent_asin": "A",
                    "timestamp": 200,
                    "rating": 5,
                },
                "turns": [
                    {
                        "user_message": "根据我的历史推荐2件",
                        "limit": 2,
                        "gold": {
                            "k": 2,
                            "hard": [{"field": "category", "op": "eq", "value": "pens"}],
                            "soft": [],
                        },
                    }
                ],
            }
        ],
    }

    def agent(request):
        assert request["profile_user_id"] == "dataset-user"
        assert request["profile_snapshot"] == profile
        assert "gold" not in json.dumps(request) and "anchor" not in json.dumps(request)
        for name in ("session_memory", "recommend_profile_pipeline"):
            with urlopen(
                Request(
                    request["fixture_url"] + "/tool",
                    data=json.dumps({"tool_name": name, "arguments": {"return_count": 2}}).encode(),
                    headers={"Content-Type": "application/json"},
                )
            ) as response:
                answer = json.load(response)
                assert answer["profile_user_id"] == "dataset-user"
        return {"turns": [{"item_ids": ["A", "B"], "outcome": "recommend"}]}

    report = run_benchmark(benchmark, agent, {"adapter_kind": "test"}, repeats=2)
    assert report["summary"]["success_rate"] == 1
    assert all(trial["profile_user_id"] == "dataset-user" for trial in report["trials"])
    assert all(
        trial["profile_snapshot_sha256"] == fingerprint(profile) for trial in report["trials"]
    )


@pytest.mark.skipif(
    not os.environ.get("RS_BENCHMARK_TEST_JAVA"), reason="需要 JDK21 和已编译 Java 工程"
)
def test_real_java_loop_keeps_dataset_profile_binding_and_reads_history():
    from pathlib import Path
    from rs_core.offline.evaluation.skill_benchmark.adapters import prepare_java_command
    from rs_core.offline.evaluation.skill_benchmark.engineering import run_java_selfcheck

    command = prepare_java_command(
        Path(__file__).resolve().parents[2], os.environ["RS_BENCHMARK_TEST_JAVA"]
    )
    for store, expected in (("Blue", ["A", "B"]), ("Red", ["B", "A"])):
        check = run_java_selfcheck(command, profile_store=store)
        assert check["baseline"]["summary"]["success_rate"] == 1
        assert check["baseline"]["summary"]["mean_ranking_score"] == pytest.approx(100)
        for trial in check["baseline"]["trials"]:
            assert trial["profile_user_id"] == f"engineering-profile-{store}"
            assert trial["runtime"]["profile_user_id"] == trial["profile_user_id"]
            assert trial["runtime"]["profile_snapshot_sha256"] == trial["profile_snapshot_sha256"]
            assert trial["turns"][0]["answer"]["item_ids"] == expected
            assert any(event["tool_name"] == "session_memory" for event in trial["tool_trace"])


@pytest.mark.parametrize(
    "leak",
    [
        "future_history",
        "cross_user_history",
        "seen_anchor",
        "cross_split_user",
        "wrong_binding",
        "profile_hash",
    ],
)
def test_dataset_validation_rejects_profile_leakage_and_broken_binding(leak):
    import copy

    catalog = [{"item_id": "A", "category": "pens"}]
    profile = {
        "profile_user_id": "u",
        "history_cutoff_exclusive": 200,
        "seen_item_ids": ["P"],
        "history": [{"user_id": "u", "parent_asin": "P", "timestamp": 100, "rating": 5}],
        "profile_preferences": {},
    }
    task = {
        "task_id": "t",
        "family_id": "f",
        "split": "test",
        "kind": "personalized",
        "profile_user_id": "u",
        "anchor_item_id": "A",
        "anchor_evidence": {"user_id": "u", "parent_asin": "A", "timestamp": 200, "rating": 5},
        "turns": [
            {
                "user_message": "推荐1件",
                "limit": 1,
                "gold": {"k": 1, "hard": [{"field": "category", "op": "eq", "value": "pens"}]},
            }
        ],
    }
    benchmark = {
        "schema_version": "rs-skill-benchmark/1",
        "catalog": catalog,
        "profiles": {"u": profile},
        "environment": {},
        "manifest": {"catalog_sha256": fingerprint(catalog)},
        "tasks": [task],
    }
    if leak == "future_history":
        profile["history"][0]["timestamp"] = 200
    elif leak == "cross_user_history":
        profile["history"][0]["user_id"] = "other"
    elif leak == "seen_anchor":
        profile["seen_item_ids"].append("A")
    elif leak == "cross_split_user":
        benchmark["tasks"].append(
            dict(copy.deepcopy(task), task_id="other", family_id="other", split="train")
        )
    elif leak == "wrong_binding":
        task["profile_user_id"] = "missing"
    benchmark["manifest"]["profiles_sha256"] = (
        "wrong" if leak == "profile_hash" else fingerprint(benchmark["profiles"])
    )
    with pytest.raises(ValueError):
        validate_benchmark(benchmark)
