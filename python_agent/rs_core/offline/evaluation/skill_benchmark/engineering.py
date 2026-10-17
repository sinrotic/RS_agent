"""仅验证工程链路：真实 Java Loop，外部模型被可控 HTTP 替身替代。不是能力评测。"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .dataset import fingerprint
from .runner import SubprocessAgent, compare_runs, run_benchmark


def run_java_selfcheck(command, *, profile_store=None):
    catalog = [
        {
            "item_id": "A",
            "title": "Example A",
            "category": "headphones",
            "price": 260,
            "currency": "CNY",
            "wireless": True,
            "weight": 150,
            "color": "black",
        },
        {
            "item_id": "B",
            "title": "Example B",
            "category": "headphones",
            "price": 290,
            "currency": "CNY",
            "wireless": True,
            "weight": 225,
            "color": "black",
        },
        {
            "item_id": "C",
            "title": "Example C",
            "category": "headphones",
            "price": 320,
            "currency": "CNY",
            "wireless": True,
            "weight": 100,
            "color": "black",
        },
    ]
    gold = {
        "k": 2,
        "hard": [
            {"field": "category", "op": "eq", "value": "headphones"},
            {"field": "price", "op": "lte", "value": 300},
            {"field": "wireless", "op": "eq", "value": True},
        ],
        "soft": [
            {"field": "weight", "op": "minimize", "best": 150, "worst": 300, "weight": 0.6},
            {"field": "color", "op": "eq", "value": "black", "weight": 0.4},
        ],
    }
    benchmark = {
        "schema_version": "rs-skill-benchmark/1",
        "catalog": catalog,
        "manifest": {"catalog_sha256": fingerprint(catalog), "human_reviewed": False},
        "environment": {"tool_call_budget": 8},
        "tasks": [
            {
                "task_id": "engineering-example",
                "family_id": "engineering",
                "kind": "engineering_only",
                "review_status": "pending",
                "split": "dev",
                "turns": [
                    {
                        "user_message": "推荐2件不超过300元的无线耳机，优先轻便和黑色，重要性6:4。",
                        "limit": 2,
                        "gold": gold,
                    }
                ],
            }
        ],
    }
    if profile_store is not None:
        if profile_store not in {"Blue", "Red"}:
            raise ValueError("工程画像只能使用 Blue/Red")
        for item, store in zip(catalog, ("Blue", "Red", "Blue")):
            item["store"] = store
        user = f"engineering-profile-{profile_store}"
        profile_snapshot = {
            "profile_user_id": user,
            "history_cutoff_exclusive": 200,
            "seen_item_ids": ["past-item"],
            "activity_count": 3,
            "history": [
                {
                    "user_id": user,
                    "parent_asin": "past-item",
                    "timestamp": 100,
                    "rating": 5,
                    "item": {"store": profile_store, "category": "headphones"},
                }
            ],
            "profile_preferences": {"preferred_store": profile_store},
        }
        benchmark["profiles"] = {user: profile_snapshot}
        benchmark["manifest"]["profiles_sha256"] = fingerprint(benchmark["profiles"])
        benchmark["manifest"]["catalog_sha256"] = fingerprint(catalog)
        benchmark["tasks"][0]["profile_user_id"] = user
        gold["soft"] = [{"field": "store", "op": "eq", "value": profile_store, "weight": 1}]

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            context = json.loads(body["messages"][0]["content"].rsplit("\n", 1)[-1])
            if "gold" in context:
                raise AssertionError("gold 泄漏到模型")
            results = context.get("tool_results", [])
            names = {result["tool_name"] for result in results}
            reverse = any(
                "工程排序反转标记" in result.get("metadata", {}).get("content", "")
                for result in results
            )
            ids = ["B", "A"] if reverse else ["A", "B"]
            if profile_store is not None:
                snapshot = context.get("benchmark_profile_snapshot", {})
                if (
                    snapshot.get("profile_user_id") != f"engineering-profile-{profile_store}"
                    or "anchor_evidence" in context
                ):
                    raise AssertionError("画像绑定未进入真实 Java 模型请求")
                if "session_memory" in names:
                    memories = [
                        result for result in results if result["tool_name"] == "session_memory"
                    ]
                    actual = memories[-1]["metadata"]
                    store = actual["profile_preferences"]["preferred_store"]
                    ids = ["A", "B"] if store == "Blue" else ["B", "A"]
                    if reverse:
                        ids.reverse()
            if profile_store is not None and "session_memory" not in names:
                name, arguments = "session_memory", {}
            elif "load_skill" not in names:
                name, arguments = "load_skill", {"skill_name": "explicit-need-recommendation"}
            elif "recommend_semantic_recall" not in names:
                name, arguments = (
                    "recommend_semantic_recall",
                    {
                        "query": "headphones",
                        "constraints": {"category": "headphones", "price_max": 300},
                        "return_count": 20,
                    },
                )
            elif "render_product_cards" not in names:
                name, arguments = "render_product_cards", {"item_ids": ids}
            else:
                name, arguments = (
                    "emit_final_answer",
                    {
                        "blocks": [
                            {
                                "type": "text",
                                "content": "这是受控模型的工程验证结果，不代表真实模型能力。",
                            },
                            {"type": "product_cards", "item_ids": ids},
                        ]
                    },
                )
            response = {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": f"check-{len(results)}",
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(arguments, ensure_ascii=False),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
            data = json.dumps(response, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = {
            "model": "controlled-http-model",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "temperature": 0,
            "seed": 0,
            "adapter_kind": "engineering_only_java_loop",
        }
        adapter = SubprocessAgent(command, timeout=60)
        baseline = run_benchmark(benchmark, adapter, config, split="dev", repeats=2)
        overlays = {
            "explicit-need-recommendation": {
                "description": "仅工程验证用候选 Skill",
                "content": "工程排序反转标记",
            }
        }
        candidate = run_benchmark(
            benchmark, adapter, config, split="dev", repeats=2, skills=overlays
        )
        return {
            "purpose": "engineering_only; external_model_is_controlled_stub",
            "baseline": baseline,
            "candidate": candidate,
            "comparison": compare_runs(baseline, candidate),
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
