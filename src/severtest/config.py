from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .domain import FruitSpec, MilestoneConfig, RoundConfig


def load_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data, hashlib.sha256(raw).hexdigest()


def load_milestone_config(path: Path) -> tuple[MilestoneConfig, str]:
    data, digest = load_json(path)
    rounds = {
        int(item["round"]): RoundConfig(
            round_number=int(item["round"]),
            vitality_cost=int(item.get("vitality_cost", 0)),
            draw_scores=tuple(int(value) for value in item["draw_scores"]),
        )
        for item in data["rounds"]
    }
    config = MilestoneConfig(
        activity_id=int(data["activity_id"]),
        activity_vary_ids=tuple(int(value) for value in data["activity_vary_ids"]),
        quality_scores={int(key): int(value) for key, value in data["quality_scores"].items()},
        innate_vary_scores={int(key): int(value) for key, value in data.get("innate_vary_scores", {}).items()},
        season_tag=int(data.get("season_tag", 0)),
        season_score=int(data.get("season_score", 0)),
        rounds=rounds,
    )
    config.validate()
    return config, digest


def load_fruit_catalog(path: Path) -> tuple[FruitSpec, ...]:
    data, _ = load_json(path)
    fruits = tuple(
        FruitSpec(
            name=str(item["name"]),
            harvest_type_id=int(item["harvest_type_id"]),
            quality=int(item["quality"]),
            activity_vary_id=int(item["activity_vary_id"]),
            innate_vary_ids=tuple(int(value) for value in item.get("innate_vary_ids", [])),
            season_tags=tuple(int(value) for value in item.get("season_tags", [])),
            weight=float(item.get("weight", 3.0)),
        )
        for item in data["fruits"]
    )
    if not fruits:
        raise ValueError("fruit catalog must contain at least one fruit")
    return fruits
