from __future__ import annotations

import re
from typing import Any


# This registry is deliberately small: each entry must already exist in go-client.
ACTION_ALIASES = {
    "加载玩家数据": "load_actor",
    "读取玩家数据": "load_actor",
    "准备玩家数据": "load_actor",
    "刷新玩家数据": "refresh_actor",
    "重新读取玩家数据": "refresh_actor",
    "发放果实": "give_harvest",
    "提交里程碑果实": "submit_milestone_v2",
    "设置团队活动积分": "set_gve_score",
    "领取团队活动奖励": "claim_gve_reward",
}


def resolve_action(step: Any) -> dict[str, Any] | None:
    if isinstance(step, dict) and isinstance(step.get("action"), str):
        return {"action": step["action"], "params": step.get("params", {}), "save_as": step.get("save_as", "")}
    if not isinstance(step, str):
        return None
    text = re.sub(r"\s+", "", step)
    for phrase, action in ACTION_ALIASES.items():
        if phrase in text:
            return {"action": action, "params": {}, "save_as": ""}
    return None


def resolve_assertion(assertion: Any) -> dict[str, Any] | None:
    if not isinstance(assertion, dict):
        return None
    required = ("name", "metric", "op", "expected")
    if not all(key in assertion for key in required):
        return None
    return {key: assertion[key] for key in required}
