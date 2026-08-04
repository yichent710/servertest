import unittest

from severtest.domain import FruitSpec, MilestoneConfig, PlanningError, RoundConfig
from severtest.planner import plan_exact_score, target_before_node


class PlannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = MilestoneConfig(
            activity_id=1,
            activity_vary_ids=(28,),
            quality_scores={1: 5, 2: 10, 3: 15},
            innate_vary_scores={},
            season_tag=0,
            season_score=0,
            rounds={1: RoundConfig(1, 0, (10, 20, 30))},
        )
        self.catalog = (
            FruitSpec("five", 1001, 1, 28),
            FruitSpec("ten", 1002, 2, 28),
            FruitSpec("fifteen", 1003, 3, 28),
        )

    def test_uses_fewest_fruits_for_exact_target(self) -> None:
        plan = plan_exact_score(
            self.config,
            self.catalog,
            round_number=1,
            initial_score=0,
            target_score=25,
        )
        self.assertEqual(25, plan.planned_score)
        self.assertEqual(2, len(plan.fruits))

    def test_calculates_target_before_node(self) -> None:
        self.assertEqual(19, target_before_node(self.config, 1, node=2, remaining=1))

    def test_rejects_unreachable_score(self) -> None:
        with self.assertRaises(PlanningError):
            plan_exact_score(
                self.config,
                self.catalog,
                round_number=1,
                initial_score=0,
                target_score=1,
            )


if __name__ == "__main__":
    unittest.main()
