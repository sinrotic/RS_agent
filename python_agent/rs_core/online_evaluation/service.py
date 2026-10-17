"""SQLite 持久旁路：幂等接收、租约重试、分层评价、候选改进队列。"""

import hashlib
import hmac
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .evaluator import evaluate
from .requirements import RequirementExtractor

MAX_EVENT_BYTES = 120_000
IMPROVEMENTS = {
    "hard_constraint_failed": "推荐前逐项检查当前明确硬条件；未知属性应核实或说明，当前要求优先于历史。",
    "unobserved_item": "最终展示仅使用本轮可信工具返回的商品 ID；缺少商品证据时先查询。",
    "duplicate_item": "最终列表按商品 ID 去重；保留真实供给不足说明。",
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _redact(text):
    text = re.sub(r"(?i)Bearer\s+\S+|(?:sk-|api[_-]?key[=:]\s*)[A-Za-z0-9_-]+", "[凭证已脱敏]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已脱敏]", text)
    return re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号已脱敏]", text)


def _redact_value(value):
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, dict):
        return {key: _redact_value(part) for key, part in value.items()}
    if isinstance(value, list):
        return [_redact_value(part) for part in value]
    return value


class OnlineEvaluation:
    """接口：submit / process_one / report / feedback / candidates / review_pack。

    仅 submit 在请求旁路执行 SQLite 入队；模型调用由独立 worker 完成。
    SQLite 是本评价模块的本地队列，不替代生产 Session/Feedback 权威存储。
    """

    def __init__(self, path, *, salt, catalog, extractor=None, judge=None, trigger_sessions=3, clock=time.time):
        if not isinstance(salt, str) or len(salt) < 16:
            raise ValueError("评价身份脱敏 salt 至少 16 字符")
        if type(trigger_sessions) is not int or trigger_sessions < 2:
            raise ValueError("候选触发至少需要两个独立 Session")
        self.path, self.salt, self.catalog = str(path), salt.encode(), catalog
        self.extractor, self.judge = extractor or RequirementExtractor(), judge
        self.trigger_sessions = trigger_sessions
        self.clock = clock
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS turns (
                    turn_key TEXT PRIMARY KEY, session_key TEXT NOT NULL, profile_key TEXT NOT NULL,
                    event_json TEXT NOT NULL, event_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL DEFAULT 0, report_json TEXT, error_code TEXT
                    ,received_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS evaluation_pending ON turns(status, available_at);
                CREATE TABLE IF NOT EXISTS feedback (
                    event_id TEXT PRIMARY KEY, turn_key TEXT NOT NULL REFERENCES turns(turn_key),
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidates (
                    candidate_id TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS failure_evidence (
                    turn_key TEXT NOT NULL, session_key TEXT NOT NULL, profile_key TEXT NOT NULL,
                    skill_version TEXT NOT NULL, model_version TEXT NOT NULL, evaluation_model TEXT NOT NULL,
                    evaluator_fingerprint TEXT NOT NULL, code TEXT NOT NULL, field TEXT NOT NULL,
                    received_at REAL NOT NULL, PRIMARY KEY(turn_key,code,field)
                );
                CREATE INDEX IF NOT EXISTS failure_window ON failure_evidence(received_at,skill_version,code);
            """)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _key(self, namespace, value):
        return hmac.new(self.salt, (namespace + ":" + value).encode(), hashlib.sha256).hexdigest()

    def submit(self, raw):
        if not isinstance(raw, dict) or len(_json(raw).encode()) > MAX_EVENT_BYTES:
            raise ValueError("事件无效或过大")
        for field in ("session_id", "turn_id", "profile_user_id", "skill_version", "model_version", "finish_reason"):
            if not isinstance(raw.get(field), str) or not 1 <= len(raw[field]) <= 200:
                raise ValueError("事件身份或版本无效")
        messages, ids, observed = raw.get("customer_messages"), raw.get("item_ids"), raw.get("observed_item_ids")
        if (not isinstance(messages, list) or not 1 <= len(messages) <= 12
                or any(not isinstance(m, str) or not m.strip() or len(m) > 6000 for m in messages)):
            raise ValueError("顾客消息无效")
        if any(not isinstance(rows, list) or len(rows) > 100
               or any(not isinstance(i, str) or not i or len(i) > 200 for i in rows)
               for rows in (ids, observed)):
            raise ValueError("商品 ID 列表无效")
        assistant = raw.get("assistant_message")
        if not isinstance(assistant, str) or len(assistant) > 20_000:
            raise ValueError("回答无效")
        tools = raw.get("tool_statuses", [])
        if (not isinstance(tools, list) or len(tools) > 100
                or any(not isinstance(t, dict) or not isinstance(t.get("tool_name"), str)
                       or not isinstance(t.get("status"), str) for t in tools)):
            raise ValueError("工具状态无效")
        degradation = raw.get("degradation_reasons", [])
        if (not isinstance(degradation, list) or len(degradation) > 20
                or any(not isinstance(reason, str) or len(reason) > 200 for reason in degradation)):
            raise ValueError("降级状态无效")
        turn_key = self._key("turn", _json([raw["session_id"], raw["turn_id"]]))
        event = {"turn_key": turn_key, "session_key": self._key("session", raw["session_id"]),
                 "profile_key": self._key("profile", raw["profile_user_id"]),
                 "customer_messages": [_redact(m) for m in messages],
                 "assistant_message": _redact(assistant), "item_ids": ids,
                 "observed_item_ids": observed,
                 "tool_statuses": [{"tool_name": _redact(t["tool_name"])[:100],
                                    "status": t["status"][:30]} for t in tools],
                 "context_truncated": raw.get("context_truncated") is True,
                 "degradation_reasons": [_redact(reason) for reason in degradation],
                 "occurred_at": str(raw.get("occurred_at", ""))[:50],
                 "skill_version": raw["skill_version"], "model_version": raw["model_version"],
                 "finish_reason": raw["finish_reason"]}
        # 接口只允许已由可信上游按权限取得的画像摘要，不接收任意 Agent context。
        if raw.get("profile_snapshot") is not None:
            snapshot = raw["profile_snapshot"]
            if (not isinstance(snapshot, dict) or snapshot.get("source") != "bound_profile_store"
                    or snapshot.get("allowed") is not True
                    or snapshot.get("bound_profile_user_id") != raw["profile_user_id"]
                    or set(snapshot) - {"source", "allowed", "bound_profile_user_id", "preferences", "history_evidence"}):
                raise ValueError("画像摘要缺少绑定权限来源")
            event["profile_snapshot"] = _redact_value({
                key: value for key, value in snapshot.items() if key != "bound_profile_user_id"
            })
        encoded = _json(event)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self._db() as db:
            previous = db.execute("SELECT event_hash FROM turns WHERE turn_key=?", (turn_key,)).fetchone()
            if previous:
                if previous["event_hash"] != digest:
                    raise ValueError("同一 Turn 的重复事件内容冲突")
                return {"turn_key": turn_key, "duplicate": True, "auto_deploy": False}
            db.execute("INSERT INTO turns(turn_key,session_key,profile_key,event_json,event_hash,received_at) VALUES(?,?,?,?,?,?)",
                       (turn_key, event["session_key"], event["profile_key"], encoded, digest, self.clock()))
        return {"turn_key": turn_key, "duplicate": False, "auto_deploy": False}

    def process_one(self):
        now = self.clock()
        lease_until = now + 180
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM turns WHERE status IN ('pending','processing') AND available_at<=? ORDER BY rowid LIMIT 1", (now,)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE turns SET status='processing',attempts=attempts+1,available_at=? WHERE turn_key=?",
                       (lease_until, row["turn_key"]))
        event = json.loads(row["event_json"])
        try:
            ids = list(dict.fromkeys(event["observed_item_ids"] + event["item_ids"]))
            if len(ids) > 100:
                raise ValueError("工具与展示商品并集过大")
            catalog = self.catalog(ids)
            report = evaluate(event, catalog, extractor=self.extractor, judge=self.judge)
            report["context_truncated"] = event["context_truncated"]
            with self._db() as db:
                updated = db.execute("UPDATE turns SET status='completed',report_json=?,error_code=NULL WHERE turn_key=? AND status='processing' AND available_at=?",
                                     (_json(report), row["turn_key"], lease_until))
                if updated.rowcount != 1:
                    return {"turn_key": row["turn_key"], "status": "lease_superseded", "scores": None, "auto_deploy": False}
                eligible = (report["skill_version"] != "unknown" and report["model_version"] != "unknown"
                            and not report.get("context_truncated")
                            and not any(f["owner"] in {"runtime", "infrastructure"} for f in report["failures"]))
                if eligible:
                    for failure in report["failures"]:
                        if failure["code"] in IMPROVEMENTS:
                            db.execute("INSERT OR IGNORE INTO failure_evidence VALUES(?,?,?,?,?,?,?,?,?,?)",
                                       (row["turn_key"], row["session_key"], row["profile_key"],
                                        report["skill_version"], report["model_version"], report["evaluation_model"],
                                        report["evaluator_fingerprint"], failure["code"], failure.get("field", ""), row["received_at"]))
            try:
                self._trigger()
            except Exception as error:
                # 候选队列异常与已经完成的评分分开；事实评价不被改成失败。
                report["candidate_trigger_error"] = type(error).__name__
            return report
        except Exception as error:
            # 模型/目录/存储异常不被伪装成顾客任务 0 分，也不记录异常正文中的密钥。
            status = "failed" if row["attempts"] + 1 >= 3 else "pending"
            with self._db() as db:
                db.execute("UPDATE turns SET status=?,error_code=?,available_at=? WHERE turn_key=? AND status='processing' AND available_at=?",
                           (status, type(error).__name__, now + 30, row["turn_key"], lease_until))
            return {"turn_key": row["turn_key"], "status": status,
                    "evaluation_error": type(error).__name__, "scores": None, "auto_deploy": False}

    def retry_failed(self, turn_key):
        """配置修复后的显式重试，不覆盖已完成评价或正在持有的租约。"""
        with self._db() as db:
            row = db.execute("SELECT status FROM turns WHERE turn_key=?", (turn_key,)).fetchone()
            if row is None:
                raise KeyError("评价 Turn 不存在")
            if row["status"] != "failed":
                raise ValueError("仅允许重试失败的评价")
            db.execute("UPDATE turns SET status='pending',attempts=0,available_at=0,error_code=NULL WHERE turn_key=?", (turn_key,))
        return {"turn_key": turn_key, "status": "pending", "auto_deploy": False}

    def report(self, turn_key):
        with self._db() as db:
            row = db.execute("SELECT status,error_code,report_json FROM turns WHERE turn_key=?", (turn_key,)).fetchone()
            if row is None:
                raise KeyError("评价 Turn 不存在")
            feedback = [json.loads(r[0]) for r in db.execute("SELECT payload FROM feedback WHERE turn_key=?", (turn_key,))]
        result = json.loads(row["report_json"]) if row["report_json"] else {"turn_key": turn_key, "scores": None}
        return result | {"status": row["status"], "evaluation_error": row["error_code"],
                         "feedback": feedback, "auto_deploy": False}

    def feedback(self, turn_key, event):
        if (not isinstance(event, dict) or not isinstance(event.get("event_id"), str)
                or not 1 <= len(event["event_id"]) <= 200
                or event.get("type") not in {"click", "like", "dislike", "why"}):
            raise ValueError("反馈事件无效")
        with self._db() as db:
            row = db.execute("SELECT event_json FROM turns WHERE turn_key=?", (turn_key,)).fetchone()
            if row is None:
                raise KeyError("评价 Turn 不存在")
            source = json.loads(row[0])
            if event.get("item_id") not in source["item_ids"]:
                raise ValueError("反馈商品不属于本次交付")
            comment = event.get("comment", "")
            if not isinstance(comment, str) or len(comment) > 3000:
                raise ValueError("反馈文本无效")
            key = self._key("feedback", event["event_id"])
            payload = {"event_id": key, "type": event["type"], "item_id": event["item_id"],
                       "comment": _redact(comment), "satisfaction": None,
                       "interpretation": "explicit_feedback_not_skill_causality"}
            encoded = _json(payload)
            previous = db.execute("SELECT turn_key,payload FROM feedback WHERE event_id=?", (key,)).fetchone()
            if previous:
                if previous[0] != turn_key or previous[1] != encoded:
                    raise ValueError("反馈事件内容冲突")
                return {"duplicate": True}
            db.execute("INSERT INTO feedback VALUES(?,?,?)", (key, turn_key, encoded))
        return {"duplicate": False}

    def _trigger(self):
        with self._db() as db:
            cutoff = self.clock() - 7 * 86400
            groups = db.execute("""SELECT skill_version,model_version,evaluation_model,evaluator_fingerprint,code,field,
                COUNT(DISTINCT session_key) AS sessions,COUNT(DISTINCT profile_key) AS profiles
                FROM failure_evidence WHERE received_at>=?
                GROUP BY skill_version,model_version,evaluation_model,evaluator_fingerprint,code,field
                HAVING COUNT(DISTINCT session_key)>=? AND COUNT(DISTINCT profile_key)>=2""",
                (cutoff, self.trigger_sessions)).fetchall()
            for group in groups:
                key = tuple(group[name] for name in ("skill_version", "model_version", "evaluation_model",
                                                    "evaluator_fingerprint", "code", "field"))
                turns = [row[0] for row in db.execute("""SELECT DISTINCT turn_key FROM failure_evidence WHERE
                    skill_version=? AND model_version=? AND evaluation_model=? AND evaluator_fingerprint=?
                    AND code=? AND field=? AND received_at>=? ORDER BY turn_key LIMIT 100""", (*key, cutoff))]
                candidate_id = hashlib.sha256(_json(key).encode()).hexdigest()
                payload = {"candidate_id": candidate_id, "baseline_skill_version": key[0],
                           "baseline_model_version": key[1], "evaluation_model": key[2],
                           "evaluator_fingerprint": key[3], "failure_code": key[4], "field": key[5],
                           "evidence_turns": turns, "evidence_limit": 100,
                           "independent_sessions": group["sessions"],
                           "independent_profiles": group["profiles"],
                           "candidate_instruction": IMPROVEMENTS[key[4]],
                           "status": "proposed_overlay_pending_review",
                           "gates": ["attribution_review", "requirements_review", "existing_benchmark_regression",
                                     "new_case_holdout", "scorer_calibration", "manual_release"],
                           "auto_deploy": False}
                db.execute("INSERT INTO candidates VALUES(?,?) ON CONFLICT(candidate_id) DO UPDATE SET payload=excluded.payload",
                           (candidate_id, _json(payload)))

    def candidates(self):
        with self._db() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM candidates ORDER BY candidate_id")]

    def diagnostics(self):
        with self._db() as db:
            counts = {row[0]: row[1] for row in db.execute("SELECT status,COUNT(*) FROM turns GROUP BY status")}
            candidates = db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        return {"turn_counts": counts, "candidate_count": candidates,
                "extraction_mode": "independent_model" if self.extractor.model is not None else "limited_rules",
                "judge_configured": self.judge is not None, "auto_deploy": False}

    def review_pack(self, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("导出条数必须为 1..500")
        with self._db() as db:
            rows = db.execute("SELECT event_json,report_json FROM turns WHERE status='completed' ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        examples = []
        for row in rows:
            event, report = json.loads(row[0]), json.loads(row[1])
            examples.append({"event": event, "evaluation": report,
                             "review": {"approved": False, "reviewer_id": None, "gold": None,
                                        "export_permission": False, "profile_scope": "not_exported"}})
        return {"schema_version": "rs-online-review/1", "examples": examples,
                "candidates": self.candidates(), "auto_deploy": False,
                "notice": "模型需求不是 gold；抽取成功与失败样本均需审核及脱敏授权后进入新评测集"}
