from __future__ import annotations

from dataclasses import dataclass


class ConfigError(ValueError):
    """Raised when a milestone configuration cannot produce safe test data."""


class PlanningError(ValueError):
    """Raised when the requested state cannot be built from available fruits."""


@dataclass(frozen=True)
class FruitSpec:
    """A reproducible fruit definition accepted by DebugGiveHarvestReq."""

    name: str
    harvest_type_id: int
    quality: int
    activity_vary_id: int
    innate_vary_ids: tuple[int, ...] = ()
    season_tags: tuple[int, ...] = ()
    weight: float = 3.0

    @property
    def vary_ids(self) -> tuple[int, ...]:
        return (self.activity_vary_id, *self.innate_vary_ids)


@dataclass(frozen=True)
class RoundConfig:
    round_number: int
    vitality_cost: int
    draw_scores: tuple[int, ...]

    @property
    def final_score(self) -> int:
        return self.draw_scores[-1]


@dataclass(frozen=True)
class MilestoneConfig:
    activity_id: int
    activity_vary_ids: tuple[int, ...]
    quality_scores: dict[int, int]
    innate_vary_scores: dict[int, int]
    season_tag: int
    season_score: int
    rounds: dict[int, RoundConfig]

    def validate(self) -> None:
        if self.activity_id <= 0:
            raise ConfigError("activity_id must be positive")
        if not self.activity_vary_ids:
            raise ConfigError("activity_vary_ids must not be empty")
        if not self.quality_scores:
            raise ConfigError("quality_scores must not be empty")
        if not self.rounds:
            raise ConfigError("rounds must not be empty")
        for number, round_config in self.rounds.items():
            if number != round_config.round_number:
                raise ConfigError(f"round key {number} does not match round_number")
            if round_config.vitality_cost < 0:
                raise ConfigError(f"round {number} vitality_cost must not be negative")
            if not round_config.draw_scores:
                raise ConfigError(f"round {number} draw_scores must not be empty")
            if any(score <= 0 for score in round_config.draw_scores):
                raise ConfigError(f"round {number} draw scores must be positive")
            if tuple(sorted(set(round_config.draw_scores))) != round_config.draw_scores:
                raise ConfigError(f"round {number} draw scores must be unique and ascending")


@dataclass(frozen=True)
class PlannedFruit:
    spec: FruitSpec
    score: int


@dataclass(frozen=True)
class PreparationPlan:
    activity_id: int
    round_number: int
    initial_score: int
    target_score: int
    fruits: tuple[PlannedFruit, ...]

    @property
    def planned_score(self) -> int:
        return sum(item.score for item in self.fruits)

    def as_dict(self) -> dict[str, object]:
        return {
            "activity_id": self.activity_id,
            "round_number": self.round_number,
            "initial_score": self.initial_score,
            "target_score": self.target_score,
            "planned_score": self.planned_score,
            "fruits": [
                {
                    "name": item.spec.name,
                    "harvest_type_id": item.spec.harvest_type_id,
                    "vary_ids": list(item.spec.vary_ids),
                    "weight": item.spec.weight,
                    "score": item.score,
                }
                for item in self.fruits
            ],
        }
