from __future__ import annotations

from .domain import ConfigError, FruitSpec, MilestoneConfig


def calculate_fruit_score(config: MilestoneConfig, fruit: FruitSpec) -> int:
    """Mirror ActMilestoneV2.CalculateHarvestScore for planning only.

    The real server response remains authoritative. The executor must stop when
    its returned score differs from this local prediction.
    """

    if fruit.activity_vary_id not in config.activity_vary_ids:
        raise ConfigError(f"fruit {fruit.name!r} does not contain an activity vary")
    try:
        score = config.quality_scores[fruit.quality]
    except KeyError as exc:
        raise ConfigError(f"fruit {fruit.name!r} uses unknown quality {fruit.quality}") from exc

    score += sum(config.innate_vary_scores.get(vary_id, 0) for vary_id in fruit.innate_vary_ids)
    if config.season_tag and config.season_tag in fruit.season_tags:
        score += config.season_score
    if score <= 0:
        raise ConfigError(f"fruit {fruit.name!r} produces a non-positive score")
    return score
