"""每个试验独占的只读工具环境；无数据库、账号、生产工具或 gold。"""

import copy
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FixtureEnvironment:
    def __init__(self, catalog, config):
        self.catalog = copy.deepcopy(catalog)
        self.config = copy.deepcopy(config)
        self.trace = []
        self.observed_item_ids = set()
        self.turn_index = 0
        self.customer_trace = []
        self._customer_next_index = 0
        self._customer_closed = False
        self._calls = 0
        self._transient_failures = config.get("transient_failure_budget", 0)
        self._lock = threading.Lock()
        self._server = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=2)

    def begin_turn(self, index):
        with self._lock:
            self.turn_index, self._calls = index, 0

    def advance_customer(self, index, answer):
        """隐藏顾客脚本只在真实澄清通过后提供下一条公开消息。"""
        from .dataset import fingerprint
        from .scoring import evaluate_turn

        with self._lock:
            turns = self.config.get("customer_turns", [])
            if (
                self._customer_closed
                or index != self._customer_next_index
                or not 0 <= index < len(turns)
            ):
                return {"done": True, "blocked": True}
            gold = turns[index]["gold"]
            blocked = False
            action = gold.get("customer_policy", {}).get("action")
            terminal_reference = False
            if action in {"clarify", "recommend_or_clarify"}:
                try:
                    observed_answer = dict(answer, observed_item_ids=sorted(self.observed_item_ids))
                    grade = evaluate_turn(self.catalog, gold, observed_answer)
                    blocked = not grade["success"]
                    terminal_reference = (
                        action == "recommend_or_clarify"
                        and grade.get("interaction_action") == "recommend"
                    )
                except (ValueError, TypeError, KeyError):
                    blocked = True
            done = blocked or terminal_reference or index + 1 == len(turns)
            self.customer_trace.append(
                {
                    "turn_index": index,
                    "answer_sha256": fingerprint(answer),
                    "blocked": blocked,
                    "done": done,
                }
            )
            self._customer_next_index += 1
            self._customer_closed = done
            if done:
                return {"done": True, "blocked": blocked}
            following = turns[index + 1]
            return {
                "done": False,
                "blocked": False,
                "next_turn": {
                    "user_message": following["user_message"],
                    "limit": following["limit"],
                },
            }

    def call(self, tool_name, arguments):
        with self._lock:
            self._calls += 1
            if self._calls > self.config.get("tool_call_budget", 16):
                answer = {"status": "FAILED", "error": "TOOL_BUDGET_EXCEEDED"}
            elif tool_name in self.config.get("unavailable_tools", []):
                answer = {"status": "FAILED", "error": "TOOL_UNAVAILABLE"}
            elif self._transient_failures and tool_name.startswith("recommend_"):
                self._transient_failures -= 1
                answer = {"status": "FAILED", "error": "TRANSIENT_FAILURE"}
            else:
                try:
                    answer = self._answer(tool_name, arguments)
                except (TypeError, ValueError, KeyError):
                    answer = {"status": "FAILED", "error": "INVALID_TOOL_ARGUMENTS"}
            if answer.get("status") == "SUCCESS" and self.config.get("untrusted_tool_text"):
                answer["untrusted_description"] = self.config["untrusted_tool_text"]
            for item in answer.get("items", []):
                self.observed_item_ids.add(item["item_id"])
            self.trace.append(
                {
                    "turn_index": self.turn_index,
                    "tool_name": tool_name,
                    "arguments": copy.deepcopy(arguments),
                    "result": copy.deepcopy(answer),
                }
            )
            return copy.deepcopy(answer)

    def _answer(self, name, arguments):
        profile = self.config.get("profile", {})
        bound_user = profile.get("profile_user_id")
        if bound_user and any(
            arguments.get(field) is not None and arguments[field] != bound_user
            for field in ("user_id", "profile_user_id")
        ):
            return {"status": "FAILED", "error": "PROFILE_USER_MISMATCH"}
        preferences = profile.get("profile_preferences", self.config.get("profile_preferences", {}))
        access = self.config.get("profile_access", {})
        permitted = access.get("allowed", True)
        if access.get("bound_profile_user_id") not in {None, bound_user}:
            return {"status": "FAILED", "error": "PROFILE_USER_MISMATCH"}
        if not permitted:
            preferences = {}
        if name == "session_memory":
            return {
                "status": "SUCCESS",
                **({"profile_user_id": bound_user} if bound_user else {}),
                "profile_preferences": preferences,
                "profile_history": profile.get("history", []) if permitted else [],
                "behavioral_preferences": profile.get("behavioral_preferences", [])
                if permitted
                else [],
                "seen_item_ids": profile.get("seen_item_ids", []) if permitted else [],
                "profile_access": access,
                "session_preferences": self.config.get("session_preferences", {}),
            }
        if name in {"rag_support", "rag_evidence_search"}:
            ids = arguments.get("candidate_item_ids", arguments.get("item_ids", []))
            evidence = [
                {"item_id": item["item_id"], "source": "frozen_catalog", "facts": item}
                for item in self.catalog
                if item["item_id"] in ids
            ]
            return {"status": "SUCCESS", "evidence": evidence}
        if name == "catalog_card":
            ids = arguments.get("item_ids", [arguments.get("item_id")])
            items = [item for item in self.catalog if item["item_id"] in ids]
            return {
                "status": "SUCCESS",
                "items": items,
                "missing_item_ids": [
                    i for i in ids if i not in {item["item_id"] for item in items}
                ],
            }
        if not name.startswith("recommend_"):
            return {"status": "FAILED", "error": "UNSUPPORTED_TOOL"}
        allowed = {
            "recommend_candidates",
            "recommend_semantic_recall",
            "recommend_profile_pipeline",
            "recommend_cold_fallback",
            "recommend_rerank_candidates",
        }
        if name not in allowed:
            return {"status": "FAILED", "error": "UNSUPPORTED_TOOL"}
        constraints = arguments.get("constraints", {})
        category = constraints.get(
            "categories", constraints.get("category", arguments.get("category"))
        )
        maximum = constraints.get("price_max", constraints.get("max_price"))
        minimum = constraints.get("price_min", constraints.get("min_price"))
        excluded = set(constraints.get("exclude_item_ids", []))
        if permitted and self.config.get("exclude_seen_items", True):
            excluded |= set(profile.get("seen_item_ids", []))
        candidate_ids = arguments.get("candidate_item_ids")
        query_terms = set(re.findall(r"[a-z0-9]+", str(arguments.get("query", "")).lower()))
        items = []
        for item in self.catalog:
            if category and (
                item.get("category") not in category
                if isinstance(category, list)
                else item.get("category") != category
            ):
                continue
            if (
                constraints.get("category_path") is not None
                and item.get("category_path") != constraints["category_path"]
            ):
                continue
            price_unknown = item.get("price") is None and "price" in self.config.get("masked_catalog_fields", [])
            if maximum is not None and not price_unknown and (item.get("price") is None or item["price"] > maximum):
                continue
            if minimum is not None and not price_unknown and (item.get("price") is None or item["price"] < minimum):
                continue
            if (
                item["item_id"] in excluded
                or candidate_ids is not None
                and item["item_id"] not in candidate_ids
            ):
                continue
            if any(
                item.get(field) != constraints[field]
                for field in ("store", "color", "currency", "connection_type", "tip_mm")
                if field in constraints
            ):
                continue
            items.append(item)

        # 固定画像偏好 + 词面召回，明确不冒充生产语义/训练排序模型。
        personalized = (
            bool(bound_user)
            and permitted
            and self.config.get("history_retrieval_role") != "disabled"
            and name != "recommend_cold_fallback"
            and not constraints.get("ignore_profile_preferences", False)
        )

        def ordering(item):
            terms = set(re.findall(r"[a-z0-9]+", item.get("title", "").lower()))
            affinity = 0.0
            if personalized:
                if preferences.get("category_scores"):
                    affinity = (0.35 if preferences.get("store_scores") else 0.7) * preferences[
                        "category_scores"
                    ].get(item.get("category"), 0)
                    affinity += 0.35 * preferences.get("store_scores", {}).get(item.get("store"), 0)
                else:
                    affinity = float(
                        preferences.get("preferred_store") is not None
                        and item.get("store") == preferences["preferred_store"]
                    )
            if self.config.get("history_retrieval_role") == "weak_reference":
                return (
                    -len(terms & query_terms),
                    item.get("price") if item.get("price") is not None else float("inf"),
                    -affinity,
                    item["item_id"],
                )
            return (
                -affinity,
                -len(terms & query_terms),
                item.get("price") if item.get("price") is not None else float("inf"),
                item["item_id"],
            )

        items.sort(key=ordering)
        count = max(1, min(50, int(arguments.get("return_count", 20))))
        return {
            "status": "SUCCESS",
            "items": items[:count],
            "recommendation_items": items[:count],
            "total_matches": len(items),
            "catalog_scope": "frozen_fixture_only",
            **({"profile_user_id": bound_user} if bound_user else {}),
            "ranking_policy": "lexical_then_price_then_history_tie/1"
            if self.config.get("history_retrieval_role") == "weak_reference"
            else "profile_affinity_then_lexical_then_price/2"
            if personalized
            else "lexical_then_price/1",
        }

    @property
    def url(self):
        """给 Java 子进程使用的随机 loopback 端口，退出上下文后关闭。"""
        if self._server is None:
            environment = self

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass

                def do_POST(self):
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        if not 0 < length <= 1_000_000:
                            raise ValueError("无效请求大小")
                        body = json.loads(self.rfile.read(length))
                        if self.path == "/turn":
                            environment.begin_turn(int(body["turn_index"]))
                            answer = {"status": "SUCCESS"}
                        elif self.path == "/tool":
                            answer = environment.call(body["tool_name"], body.get("arguments", {}))
                        elif self.path == "/customer":
                            answer = environment.advance_customer(
                                int(body["turn_index"]), body["answer"]
                            )
                        else:
                            raise ValueError("未知路径")
                        data = json.dumps(answer, ensure_ascii=False, allow_nan=False).encode(
                            "utf-8"
                        )
                        self.send_response(200)
                    except (ValueError, TypeError, KeyError):
                        data = b'{"status":"FAILED","error":"INVALID_REQUEST"}'
                        self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

            self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            self._thread = threading.Thread(target=lambda: self._server.serve_forever(poll_interval=0.02), daemon=True)
            self._thread.start()
        return f"http://127.0.0.1:{self._server.server_port}"
