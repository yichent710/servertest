import unittest

from severtest.domain import FruitSpec, MilestoneConfig, RoundConfig
from severtest.scoring import calculate_fruit_score


class ScoringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = MilestoneConfig(
            activity_id=1,
            activity_vary_ids=(28,),
            quality_scores={1: 5, 2: 10},
            innate_vary_scores={1: 5, 16: 10},
            season_tag=3,
            season_score=5,
            rounds={1: RoundConfig(1, 0, (10, 20, 30))},
        )

    def test_combines_quality_innate_and_season_scores(self) -> None:
        fruit = FruitSpec("fruit", 1001, 2, 28, (1, 16), (3,))
        self.assertEqual(30, calculate_fruit_score(self.config, fruit))


if __name__ == "__main__":
    unittest.main()
