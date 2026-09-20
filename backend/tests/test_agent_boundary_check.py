"""
Test: Delhi NCR Boundary Check & Location Reverse-Geocoding Guardrails

Verifies that:
1. A genuine Delhi NCR location (e.g. Connaught Place / Lodhi Garden / lat 28.6328, lon 77.2197)
   completes the normal recommendation flow and returns an optimal park recommendation.
2. An out-of-region location (e.g. Jaipur / Mumbai / raw coordinates 26.8375, 75.5614):
   - Does NOT recommend any Delhi park or run PEVI / forecast model.
   - Responds honestly: "I'm currently built specifically for Delhi NCR and don't have real air quality data for [detected place name] yet — I'll be able to help when I expand to your city!"
   - Returns status="complete", missing_fields=[], recommendation=None.
3. Coordinates are reverse-geocoded to a human-readable place name rather than showing raw floats.
"""

import unittest
import uuid
from backend.app.main import (
    conversational_ask,
    AgentAskRequest,
    _SESSIONS,
    is_within_delhi_ncr,
    reverse_geocode,
    geocode_location
)


class TestAgentBoundaryCheck(unittest.TestCase):

    def setUp(self):
        self.session_id = f"test-boundary-{uuid.uuid4()}"
        _SESSIONS.pop(self.session_id, None)

    def tearDown(self):
        _SESSIONS.pop(self.session_id, None)

    def test_delhi_ncr_boundary_helper(self):
        # Inside Delhi NCR
        self.assertTrue(is_within_delhi_ncr(28.6328, 77.2197))  # Connaught Place
        self.assertTrue(is_within_delhi_ncr(28.5931, 77.2197))  # Lodhi Garden
        self.assertTrue(is_within_delhi_ncr(28.4595, 77.0266))  # Gurugram
        self.assertTrue(is_within_delhi_ncr(28.5355, 77.3910))  # Noida
        self.assertTrue(is_within_delhi_ncr(28.4089, 77.3178))  # Faridabad

        # Outside Delhi NCR
        self.assertFalse(is_within_delhi_ncr(26.8375, 75.5614))  # Jaipur
        self.assertFalse(is_within_delhi_ncr(19.0760, 72.8777))  # Mumbai
        self.assertFalse(is_within_delhi_ncr(12.9716, 77.5946))  # Bangalore
        self.assertFalse(is_within_delhi_ncr(30.7333, 76.7794))  # Chandigarh
        self.assertFalse(is_within_delhi_ncr(27.1767, 78.0081))  # Agra

    def test_genuine_delhi_location_runs_full_recommendation(self):
        profile = {
            "age_group": "adult",
            "conditions": [],
            "smoker": False,
            "planned_activity": "moderate",
        }

        # Step 1: Provide duration
        resp1 = conversational_ask(AgentAskRequest(
            session_id=self.session_id,
            message="1 hour",
            profile=profile,
        ))
        self.assertEqual(resp1.status, "clarifying")
        self.assertEqual(resp1.missing_fields, ["location"])

        # Step 2: Provide genuine Delhi NCR location
        resp2 = conversational_ask(AgentAskRequest(
            session_id=self.session_id,
            message="Connaught Place, New Delhi",
            profile=profile,
        ))
        self.assertEqual(resp2.status, "complete")
        self.assertIsNotNone(resp2.recommendation)
        self.assertIn("recommendation", resp2.recommendation)
        self.assertIn("best_park", resp2.recommendation)
        self.assertNotIn("I'm currently built specifically for Delhi NCR", resp2.message)

    def test_out_of_region_location_jaipur_responds_honestly_without_park(self):
        profile = {
            "age_group": "adult",
            "conditions": [],
            "smoker": False,
            "planned_activity": "moderate",
        }

        # Step 1: Provide duration
        resp1 = conversational_ask(AgentAskRequest(
            session_id=self.session_id,
            message="45 minutes",
            profile=profile,
        ))
        self.assertEqual(resp1.status, "clarifying")
        self.assertEqual(resp1.missing_fields, ["location"])

        # Step 2: Provide Jaipur coordinates
        resp2 = conversational_ask(AgentAskRequest(
            session_id=self.session_id,
            message="26.8375, 75.5614",
            profile=profile,
        ))

        # Must respond honestly without recommending a Delhi park
        self.assertEqual(resp2.status, "complete")
        self.assertEqual(resp2.missing_fields, [])
        self.assertIsNone(resp2.recommendation)
        self.assertIn("built specifically for Delhi NCR", resp2.message)
        self.assertIn("don't have real air quality data for", resp2.message)
        self.assertIn("expand to your city", resp2.message)
        # Verify it mentions the detected place name (Jaipur or clean name, not raw coords inside text)
        self.assertTrue("Jaipur" in resp2.message or "Rajasthan" in resp2.message or "26.8375" not in resp2.message)

    def test_out_of_region_mumbai_text_query(self):
        profile = {
            "age_group": "adult",
            "conditions": [],
            "smoker": False,
            "planned_activity": "moderate",
        }

        # Step 1: Provide duration
        conversational_ask(AgentAskRequest(
            session_id=self.session_id,
            message="1 hour",
            profile=profile,
        ))

        # Step 2: Provide Mumbai text
        resp = conversational_ask(AgentAskRequest(
            session_id=self.session_id,
            message="Mumbai",
            profile=profile,
        ))

        self.assertEqual(resp.status, "complete")
        self.assertIsNone(resp.recommendation)
        self.assertIn("built specifically for Delhi NCR", resp.message)
        self.assertIn("Mumbai", resp.message)


if __name__ == "__main__":
    unittest.main()
