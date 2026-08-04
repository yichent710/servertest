from __future__ import annotations

from .domain import FruitSpec, MilestoneConfig, PlannedFruit, PlanningError, PreparationPlan
from .scoring import calculate_fruit_score


def plan_exact_score(
    config: MilestoneConfig,
    catalog: tuple[FruitSpec, ...],
    *,
    round_number: int,
    initial_score: int,
    target_score: int,
    max_fruits: int = 30,
) -> PreparationPlan:
    """Find a deterministic, minimal fruit combination for an exact score.

    Dynamic programming is used because milestone scores are small integers.
    Ties retain catalog order, keeping generated plans stable across runs.
    """

    round_config = config.rounds.get(round_number)
    if round_config is None:
        raise PlanningError(f"round {round_number} is not configured")
    if not 0 <= initial_score <= target_score <= round_config.final_score:
        raise PlanningError(
            f"scores must satisfy 0 <= initial <= target <= {round_config.final_score}"
        )
    required = target_score - initial_score
    if required == 0:
        return PreparationPlan(config.activity_id, round_number, initial_score, target_score, ())

    options = tuple(PlannedFruit(spec, calculate_fruit_score(config, spec)) for spec in catalog)
    best: list[tuple[PlannedFruit, ...] | None] = [None] * (required + 1)
    best[0] = ()
    for score in range(1, required + 1):
        for option in options:
            previous_score = score - option.score
            if previous_score < 0 or best[previous_score] is None:
                continue
            candidate = (*best[previous_score], option)
            if len(candidate) > max_fruits:
                continue
            if best[score] is None or len(candidate) < len(best[score]):
                best[score] = candidate

    fruits = best[required]
    if fruits is None:
        available = sorted({option.score for option in options})
        raise PlanningError(
            f"cannot build exact score {required} with available fruit scores {available}"
        )
    return PreparationPlan(config.activity_id, round_number, initial_score, target_score, fruits)


def target_before_node(config: MilestoneConfig, round_number: int, node: int, remaining: int) -> int:
    round_config = config.rounds.get(round_number)
    if round_config is None:
        raise PlanningError(f"round {round_number} is not configured")
    if not 1 <= node <= len(round_config.draw_scores):
        raise PlanningError(f"node must be between 1 and {len(round_config.draw_scores)}")
    if remaining <= 0:
        raise PlanningError("remaining must be positive")
    target = round_config.draw_scores[node - 1] - remaining
    if target < 0:
        raise PlanningError("remaining is larger than the selected node score")
    return target
