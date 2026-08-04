from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..domain import FruitSpec


@dataclass(frozen=True)
class CreatedFruit:
    bag_id: int
    predicted_score: int


class ServerAdapter(ABC):
    """Boundary around SunnyIsland's private client protocol.

    Implementations must use server requests through the Actor main loop. They
    must never mutate MongoDB or Redis directly.
    """

    @abstractmethod
    def connect(self, uid: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def give_harvest(self, fruit: FruitSpec, predicted_score: int) -> CreatedFruit:
        raise NotImplementedError

    @abstractmethod
    def submit_fruits(self, activity_id: int, bag_ids: list[int], force: bool = False) -> int:
        """Return the score accepted by the server."""
        raise NotImplementedError
