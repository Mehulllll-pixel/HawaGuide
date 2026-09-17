"""
===================================================================================================
Test: Personalization Consistency Across Agent Tools (Stale-Formula Regression Test)
===================================================================================================

Target Bug:
-----------
In earlier iterations, `compute_personalized_risk()` was updated to the full 5-factor formula
(age × condition × smoker × activity × duration), but `get_park_options()` temporarily used a
stale 3-factor calculation, leading to inconsistent Personalized PEVI numbers for the same green space.

This test asserts:
For identical input profiles (varying across age, condition, smoker, activity, duration),
the Personalized PEVI calculated directly via `compute_personalized_risk()` for a park's base PEVI
matches the `personalized_pevi` returned inside `get_park_options()` for that exact same park.
===================================================================================================
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ml.agent_tools import compute_personalized_risk, get_park_options


class TestAgentPersonalizationConsistency(unittest.TestCase):

    def test_personalization_formula_identical_across_tools(self):
        """
        Verify that compute_personalized_risk() and get_park_options() produce identical
        personalized PEVI values for the same park under multiple test profiles.
        """
        test_profiles = [
            {
                "name": "Elderly Smoker with Cardiac Condition (Vigorous 1.5h)",
                "age_group": "elderly",
                "conditions": ["cardiac"],
                "smoker": True,
                "planned_activity": "vigorous",
                "duration_hours": 1.5
            },
            {
                "name": "Child with Asthma Non-Smoker (Rest 0.5h)",
                "age_group": "child",
                "conditions": ["asthma"],
                "smoker": False,
                "planned_activity": "rest",
                "duration_hours": 0.5
            },
            {
                "name": "Adult Healthy Non-Smoker (Moderate 2.0h)",
                "age_group": "adult",
                "conditions": [],
                "smoker": False,
                "planned_activity": "moderate",
                "duration_hours": 2.0
            }
        ]

        # Use Connaught Place coordinates
        start_lat = 28.6328
        start_lon = 77.2197

        for profile in test_profiles:
            with self.subTest(profile=profile["name"]):
                parks = get_park_options(
                    lat=start_lat,
                    lon=start_lon,
                    age_group=profile["age_group"],
                    conditions=profile["conditions"],
                    smoker=profile["smoker"],
                    planned_activity=profile["planned_activity"],
                    duration_hours=profile["duration_hours"],
                    alpha=0.5,
                    top_k=5
                )

                self.assertGreater(len(parks), 0, "get_park_options must return candidate parks")

                for park in parks:
                    base_pevi = park["base_pevi"]
                    tool_pers_pevi = park["personalized_pevi"]
                    tool_band = park["personalized_risk_band"]

                    # Compute directly via compute_personalized_risk()
                    direct_result = compute_personalized_risk(
                        base_pevi=base_pevi,
                        age_group=profile["age_group"],
                        conditions=profile["conditions"],
                        smoker=profile["smoker"],
                        planned_activity=profile["planned_activity"],
                        duration_hours=profile["duration_hours"]
                    )

                    expected_pevi = direct_result["personalized_pevi"]
                    expected_band = direct_result["personalized_risk_band"]

                    self.assertAlmostEqual(
                        tool_pers_pevi, expected_pevi, places=2,
                        msg=f"Personalized PEVI mismatch for {park['name']} in {profile['name']}: "
                            f"get_park_options gave {tool_pers_pevi}, compute_personalized_risk gave {expected_pevi}"
                    )
                    self.assertEqual(
                        tool_band, expected_band,
                        msg=f"Risk band mismatch for {park['name']} in {profile['name']}: "
                            f"get_park_options gave {tool_band}, compute_personalized_risk gave {expected_band}"
                    )

    def test_exact_hand_calculated_ground_truth_multipliers(self):
        """
        Verify known ground-truth input/output pairs against exact manual arithmetic
        to ensure no shared formula bug between functions:
        - age_group (adult: 1.0, child: 1.3, elderly: 1.3)
        - condition (healthy: 1.0, asthma/respiratory/cardiac/copd: 1.5)
        - smoker (False: 1.0, True: 1.25)
        - activity (rest: 1.0, moderate: 1.3, vigorous: 1.6)
        - duration (1.0 + 0.15 * duration_hours)
        """
        # Ground Truth Case 1: Elderly, Respiratory, Moderate, 2.0h, Non-smoker
        # Mult = 1.3 (age) * 1.5 (cond) * 1.0 (smoker) * 1.3 (act) * (1 + 0.15*2.0 = 1.30) = 3.2955
        gt1 = compute_personalized_risk(
            base_pevi=4.0,
            age_group="elderly",
            conditions=["respiratory"],
            smoker=False,
            planned_activity="moderate",
            duration_hours=2.0
        )
        self.assertAlmostEqual(gt1["multipliers"]["age_multiplier"], 1.3, places=3)
        self.assertAlmostEqual(gt1["multipliers"]["condition_multiplier"], 1.5, places=3)
        self.assertAlmostEqual(gt1["multipliers"]["smoker_multiplier"], 1.0, places=3)
        self.assertAlmostEqual(gt1["multipliers"]["activity_multiplier"], 1.3, places=3)
        self.assertAlmostEqual(gt1["multipliers"]["duration_multiplier"], 1.30, places=3)
        self.assertAlmostEqual(gt1["multipliers"]["total_compound_multiplier"], 3.296, places=2)
        self.assertAlmostEqual(gt1["personalized_pevi"], 13.18, places=2)
        self.assertEqual(gt1["personalized_risk_band"], "Extreme (Band 4)")

        # Ground Truth Case 2: Child, Asthma, Rest, 1.0h, Non-smoker
        # Mult = 1.3 * 1.5 * 1.0 * 1.0 * 1.15 = 2.2425
        gt2 = compute_personalized_risk(
            base_pevi=3.0,
            age_group="child",
            conditions=["asthma"],
            smoker=False,
            planned_activity="rest",
            duration_hours=1.0
        )
        self.assertAlmostEqual(gt2["multipliers"]["total_compound_multiplier"], 2.243, places=2)
        self.assertAlmostEqual(gt2["personalized_pevi"], 6.73, places=2)
        self.assertEqual(gt2["personalized_risk_band"], "Moderate (Band 2)")

        # Ground Truth Case 3: Adult, Healthy, Vigorous, 1.0h, Smoker
        # Mult = 1.0 * 1.0 * 1.25 * 1.6 * 1.15 = 2.3000
        gt3 = compute_personalized_risk(
            base_pevi=2.0,
            age_group="adult",
            conditions=[],
            smoker=True,
            planned_activity="vigorous",
            duration_hours=1.0
        )
        self.assertAlmostEqual(gt3["multipliers"]["total_compound_multiplier"], 2.300, places=2)
        self.assertAlmostEqual(gt3["personalized_pevi"], 4.60, places=2)
        self.assertEqual(gt3["personalized_risk_band"], "Low (Band 1)")


if __name__ == "__main__":
    unittest.main()
