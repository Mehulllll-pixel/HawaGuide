"""
===================================================================================================
Test: Agent Multi-Turn Session Memory (Context Merging)
===================================================================================================

Target Capability:
------------------
Verify that `_SESSIONS` memory retains state across multiple turns with the same `session_id`.
When a user provides partial fields in Turn 1 (e.g., demographic info: elderly, asthma, smoker)
and finishes supplying remaining fields in Turn 2 (e.g., location, activity, duration), the agent:
1. Keeps Turn 1 fields in session memory without re-asking for them.
2. In Turn 2, merges the new fields and triggers the complete recommendation workflow.
3. Uses the full combined profile (including Turn 1's age/condition/smoker multipliers) in the calculation.
===================================================================================================
"""

import sys
import unittest
import uuid
from unittest.mock import patch
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.main import conversational_ask, AgentAskRequest, _SESSIONS


class TestAgentSessionMemory(unittest.TestCase):

    def setUp(self):
        self.session_id = f"test-mem-{uuid.uuid4()}"

    def tearDown(self):
        _SESSIONS.pop(self.session_id, None)

    @patch("backend.app.main._extract_fields_from_text")
    def test_multi_turn_session_memory_retention(self, mock_extract):
        """
        Turn 1: User gives age_group='elderly', conditions=['asthma'], smoker=True.
        Turn 2: User gives lat=28.5931, lon=77.2197, planned_activity='moderate', duration_hours=1.0.
        Verify that Turn 1's fields are remembered in Turn 2 and full recommendation executes.
        """
        # --- TURN 1 ---
        mock_extract.return_value = {
            "age_group": "elderly",
            "conditions": ["asthma"],
            "smoker": True
        }

        req1 = AgentAskRequest(
            session_id=self.session_id,
            message="I am a senior citizen with asthma and I smoke."
        )
        resp1 = conversational_ask(req1)

        self.assertEqual(resp1.status, "clarifying")
        self.assertIn("location", resp1.missing_fields)
        self.assertNotIn("age group (adult / child / elderly)", resp1.missing_fields)

        # Check session store
        stored = _SESSIONS.get(self.session_id, {})
        self.assertEqual(stored.get("age_group"), "elderly")
        self.assertEqual(stored.get("conditions"), ["asthma"])
        self.assertEqual(stored.get("smoker"), True)

        # --- TURN 2 ---
        mock_extract.return_value = {
            "lat": 28.5931,
            "lon": 77.2197,
            "planned_activity": "moderate",
            "duration_hours": 1.0
        }

        req2 = AgentAskRequest(
            session_id=self.session_id,
            message="I am at Lodhi Garden and want to take a 1 hour walk."
        )
        resp2 = conversational_ask(req2)

        # Turn 2 must complete because all required fields are now present!
        self.assertEqual(resp2.status, "complete", f"Expected 'complete', got '{resp2.status}' with msg: {resp2.message}")
        self.assertIsNotNone(resp2.recommendation)

        rec = resp2.recommendation
        self.assertIn("multipliers", rec)
        # Elderly = 1.3, Asthma = 1.5, Smoker = 1.25
        self.assertEqual(rec["multipliers"]["age_multiplier"], 1.3)
        self.assertEqual(rec["multipliers"]["condition_multiplier"], 1.5)
        self.assertEqual(rec["multipliers"]["smoker_multiplier"], 1.25)


if __name__ == "__main__":
    unittest.main()
