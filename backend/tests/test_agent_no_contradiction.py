"""
===================================================================================================
Test: Agent No-Contradiction Guardrail (Bug 1 Regression Test)
===================================================================================================

Target Bug:
-----------
In earlier iterations, when a user started in an Extreme risk area (e.g. Base PEVI = 12.0) and the
agent recommended a safer destination park (e.g. Lodhi Garden, Moderate risk, Band 2), the explanation
text mistakenly described the park using the starting location's risk band ("Conditions are Extreme...").

This test asserts:
1. In a scenario where starting location is Extreme risk but candidate park is Moderate/Low risk (Tier 1),
   the final explanation text explicitly reports the candidate park's actual band (e.g. "Moderate (Band 2)").
2. The explanation text does NOT mention the starting location's risk band ("Extreme") when presenting
   the favorable destination.
===================================================================================================
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ml.agent_graph import explain_node, evaluate_recommendation_tier, AgentState


class TestAgentNoContradiction(unittest.TestCase):

    def test_tier1_destination_does_not_mention_extreme_start_risk(self):
        """
        Starting location is Extreme risk (PEVI=12.0, Band 4).
        Candidate park is Lodhi Garden (Personalized PEVI=6.5, Moderate / Band 2).
        The explain_node output must describe Lodhi Garden as Moderate, NOT Extreme.
        """
        candidate_parks = [
            {
                "name": "Lodhi Garden",
                "distance_km": 3.2,
                "base_pevi": 3.5,
                "personalized_pevi": 6.5,
                "personalized_risk_band": "Moderate (Band 2)",
                "advisory_guidance": "Acceptable air quality for outdoor activities.",
                "score": 0.15
            }
        ]

        # Forecast shows stable/favorable conditions
        forecast_data = [
            {"hour_ahead": h, "forecast_pm25_ugm3": 25.0 + h, "delta_from_now": float(h), "trend": "Stable"}
            for h in range(1, 7)
        ]

        # Evaluate Tier
        tier_info = evaluate_recommendation_tier(
            candidate_parks=candidate_parks,
            forecast_list=forecast_data,
            current_pm25=85.0,  # High starting PM2.5
            compound_multiplier=1.0
        )

        self.assertEqual(tier_info["tier"], "TIER_1", "Low/Moderate destination must trigger TIER_1")

        state: AgentState = {
            "lat": 28.6328,
            "lon": 77.2197,
            "age_group": "adult",
            "conditions": [],
            "smoker": False,
            "planned_activity": "moderate",
            "duration_hours": 1.0,
            "alpha": 0.5,
            "current_pevi_data": {
                "location_name": "Pollution Hotspot",
                "pevi_value": 12.0,
                "personalized_risk_band": "Extreme (Band 4)",
                "pollutants": {"pm25_ugm3": 85.0}
            },
            "forecast_data": forecast_data,
            "personalized_risk_data": {
                "personalized_pevi": 12.0,
                "personalized_risk_band": "Extreme (Band 4)",
                "multipliers": {"total_compound_multiplier": 1.0}
            },
            "candidate_parks": candidate_parks,
            "reasoning_analysis": {
                "tier_info": tier_info,
                "tier": "TIER_1"
            },
            "recommendation_text": "",
            "node_trace": []
        }

        output = explain_node(state)
        rec_text = output["recommendation_text"]

        # Assertions
        self.assertIn("Lodhi Garden", rec_text)
        self.assertIn("Moderate (Band 2)", rec_text, "Explanation must contain destination park's actual Moderate band")
        self.assertNotIn("Extreme", rec_text, "Explanation must NOT reference starting location's Extreme band")
        self.assertNotIn("Band 4", rec_text)


if __name__ == "__main__":
    unittest.main()
