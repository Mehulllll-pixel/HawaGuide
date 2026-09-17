"""
===================================================================================================
Test: Agent 3-Tier Recommendation Logic
===================================================================================================

Target Logic Verification:
--------------------------
1. TIER 1 (Go Now - Favorable):
   - Best candidate park is currently Low (Band 1) or Moderate (Band 2) risk.
   - Response tier: TIER_1
   - Tone: Immediate, unreserved recommendation to visit now without wait caveats.

2. TIER 2 (Wait for Window - Crossing into Better Band):
   - Best candidate park is currently High (Band 3) or Extreme (Band 4) risk,
     BUT 6-hour forecast trajectory shows conditions improving to Low/Moderate (or better band).
   - Response tier: TIER_2
   - Tone: Suggests waiting until the projected improvement window ("Consider waiting until X hours...").

3. TIER 3 (No Meaningful Improvement - Stay Indoor / Off-Peak):
   - Best candidate park is currently High/Extreme risk, and trajectory remains in High/Extreme for all 6 hours.
   - Response tier: TIER_3
   - Tone: Transparent, honest advice that waiting in the next 6 hours won't help enough,
     suggesting indoor activities or checking back later.
===================================================================================================
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ml.agent_graph import evaluate_recommendation_tier, explain_node, AgentState


class TestAgentTieredLogic(unittest.TestCase):

    def test_scenario_1_tier_1_favorable_now(self):
        """
        Scenario 1: Candidate park has Moderate risk right now.
        Expected: TIER_1, recommendation to go now without wait instructions.
        """
        candidate_parks = [
            {
                "name": "Lodhi Garden",
                "distance_km": 2.5,
                "base_pevi": 3.2,
                "personalized_pevi": 5.5,
                "personalized_risk_band": "Moderate (Band 2)",
                "advisory_guidance": "Acceptable air quality for outdoor activities.",
                "score": 0.1
            }
        ]
        forecasts = [
            {"hour_ahead": h, "forecast_pm25_ugm3": 25.0, "delta_from_now": 0.0, "trend": "Stable"}
            for h in range(1, 7)
        ]

        tier_info = evaluate_recommendation_tier(
            candidate_parks=candidate_parks,
            forecast_list=forecasts,
            current_pm25=25.0,
            compound_multiplier=1.0
        )

        self.assertEqual(tier_info["tier"], "TIER_1")
        self.assertEqual(tier_info["recommended_park"], "Lodhi Garden")

        state: AgentState = {
            "lat": 28.59, "lon": 77.21, "age_group": "adult", "conditions": [], "smoker": False,
            "planned_activity": "moderate", "duration_hours": 1.0, "alpha": 0.5,
            "current_pevi_data": {"pevi_value": 3.2, "pollutants": {"pm25_ugm3": 25.0}},
            "forecast_data": forecasts,
            "personalized_risk_data": {"personalized_pevi": 5.5, "multipliers": {"total_compound_multiplier": 1.0}},
            "candidate_parks": candidate_parks,
            "reasoning_analysis": {"tier_info": tier_info, "tier": "TIER_1"},
            "recommendation_text": "", "node_trace": []
        }
        res = explain_node(state)
        rec_text = res["recommendation_text"]

        self.assertIn("Lodhi Garden", rec_text)
        self.assertIn("right now", rec_text)
        self.assertNotIn("Consider waiting", rec_text)

    def test_scenario_2_tier_2_improves_within_6h(self):
        """
        Scenario 2: Candidate park is currently High (Band 3) with PEVI=8.5,
        but forecast shows PM2.5 dropping by 30 ug/m3 at t+3h, bringing projected PEVI to Moderate (Band 2).
        Expected: TIER_2, best_hour=3, wait advice.
        """
        candidate_parks = [
            {
                "name": "Sanjay Van",
                "distance_km": 4.0,
                "base_pevi": 5.2,
                "personalized_pevi": 7.8,
                "personalized_risk_band": "High (Band 3)",
                "advisory_guidance": "Sensitive groups should reduce prolonged outdoor exertion.",
                "score": 0.3
            }
        ]
        # Current PM2.5 = 60, stays elevated at t+1 and t+2, then drops to 20 at t+3h
        current_pm25 = 60.0
        forecasts = [
            {"hour_ahead": 1, "forecast_pm25_ugm3": 60.0},  # proj_pers = 7.80 (High, Band 3)
            {"hour_ahead": 2, "forecast_pm25_ugm3": 58.0},  # proj_pers = 7.78 (High, Band 3)
            {"hour_ahead": 3, "forecast_pm25_ugm3": 20.0},  # proj_pers = 7.52 (Crosses into Moderate, Band 2)
            {"hour_ahead": 4, "forecast_pm25_ugm3": 22.0},
            {"hour_ahead": 5, "forecast_pm25_ugm3": 24.0},
            {"hour_ahead": 6, "forecast_pm25_ugm3": 25.0},
        ]

        tier_info = evaluate_recommendation_tier(
            candidate_parks=candidate_parks,
            forecast_list=forecasts,
            current_pm25=current_pm25,
            compound_multiplier=1.5
        )

        self.assertEqual(tier_info["tier"], "TIER_2")
        self.assertEqual(tier_info["improved_hour"], 3)
        self.assertIn("Moderate", tier_info["improved_band"])

        state: AgentState = {
            "lat": 28.52, "lon": 77.17, "age_group": "elderly", "conditions": ["asthma"], "smoker": False,
            "planned_activity": "moderate", "duration_hours": 1.0, "alpha": 0.5,
            "current_pevi_data": {"pevi_value": 4.5, "pollutants": {"pm25_ugm3": 65.0}},
            "forecast_data": forecasts,
            "personalized_risk_data": {"personalized_pevi": 8.5, "multipliers": {"total_compound_multiplier": 1.8}},
            "candidate_parks": candidate_parks,
            "reasoning_analysis": {"tier_info": tier_info, "tier": "TIER_2"},
            "recommendation_text": "", "node_trace": []
        }
        res = explain_node(state)
        rec_text = res["recommendation_text"]

        self.assertIn("Consider waiting", rec_text)
        self.assertIn("3 hours from now", rec_text)

    def test_scenario_3_tier_3_stays_elevated_all_6h(self):
        """
        Scenario 3: Candidate park is currently Extreme (Band 4) with PEVI=14.0,
        and PM2.5 stays severe (90+ ug/m3) across all 6 hours.
        Expected: TIER_3, honest advice that waiting in next 6h won't help enough, indoor recommended.
        """
        candidate_parks = [
            {
                "name": "Swarna Jayanti Park",
                "distance_km": 6.0,
                "base_pevi": 6.8,
                "personalized_pevi": 14.0,
                "personalized_risk_band": "Extreme (Band 4)",
                "advisory_guidance": "Avoid outdoor physical activities.",
                "score": 0.8
            }
        ]
        current_pm25 = 95.0
        forecasts = [
            {"hour_ahead": h, "forecast_pm25_ugm3": 95.0 + (h * 2.0)}
            for h in range(1, 7)
        ]

        tier_info = evaluate_recommendation_tier(
            candidate_parks=candidate_parks,
            forecast_list=forecasts,
            current_pm25=current_pm25,
            compound_multiplier=2.0
        )

        self.assertEqual(tier_info["tier"], "TIER_3")

        state: AgentState = {
            "lat": 28.64, "lon": 77.36, "age_group": "adult", "conditions": ["copd"], "smoker": True,
            "planned_activity": "vigorous", "duration_hours": 1.5, "alpha": 0.5,
            "current_pevi_data": {"pevi_value": 6.8, "pollutants": {"pm25_ugm3": 95.0}},
            "forecast_data": forecasts,
            "personalized_risk_data": {"personalized_pevi": 14.0, "multipliers": {"total_compound_multiplier": 2.0}},
            "candidate_parks": candidate_parks,
            "reasoning_analysis": {"tier_info": tier_info, "tier": "TIER_3"},
            "recommendation_text": "", "node_trace": []
        }
        res = explain_node(state)
        rec_text = res["recommendation_text"]

        self.assertIn("aren't expected to improve enough", rec_text)
        self.assertIn("indoor", rec_text.lower())


if __name__ == "__main__":
    unittest.main()
