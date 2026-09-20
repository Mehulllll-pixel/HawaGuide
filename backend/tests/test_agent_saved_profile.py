"""
Test: Saved Profile Seeding via /agent/ask

Verifies that when a client passes a pre-saved profile in `AgentAskRequest`:
1. `age_group`, `conditions`, `smoker`, and `planned_activity` are pre-seeded in `_SESSIONS`.
2. Sequential clarification skips those 4 fields and directly asks for `duration_hours` and `location`.
3. `collected_profile` is returned in `AgentAskResponse`.
"""

import unittest
import uuid
from backend.app.main import conversational_ask, AgentAskRequest, _SESSIONS


class TestAgentSavedProfile(unittest.TestCase):

    def setUp(self):
        self.session_id = f"test-prof-{uuid.uuid4()}"
        _SESSIONS.pop(self.session_id, None)

    def tearDown(self):
        _SESSIONS.pop(self.session_id, None)

    def test_saved_profile_skips_profile_questions(self):
        saved_profile = {
            "age_group": "elderly",
            "conditions": ["respiratory"],
            "smoker": False,
            "planned_activity": "moderate",
        }

        # Turn 1: User asks general question with saved profile attached
        req1 = AgentAskRequest(
            session_id=self.session_id,
            message="Find me a quiet park",
            profile=saved_profile,
        )
        resp1 = conversational_ask(req1)

        self.assertEqual(resp1.status, "clarifying")
        # The next missing field must be duration_hours (not age_group, conditions, etc.)
        self.assertEqual(resp1.missing_fields[0], "duration_hours")
        self.assertIn("duration_hours", resp1.missing_fields)
        self.assertIn("location", resp1.missing_fields)
        self.assertNotIn("age_group", resp1.missing_fields)
        self.assertNotIn("conditions", resp1.missing_fields)
        self.assertNotIn("smoker", resp1.missing_fields)
        self.assertNotIn("planned_activity", resp1.missing_fields)

        # Turn 2: User provides duration
        req2 = AgentAskRequest(
            session_id=self.session_id,
            message="45 minutes",
        )
        resp2 = conversational_ask(req2)

        self.assertEqual(resp2.status, "clarifying")
        self.assertEqual(resp2.missing_fields[0], "location")

        # Turn 3: User provides location via coordinates
        req3 = AgentAskRequest(
            session_id=self.session_id,
            message="28.5931, 77.2197",
        )
        resp3 = conversational_ask(req3)

        self.assertEqual(resp3.status, "complete")
        self.assertIsNotNone(resp3.recommendation)
        self.assertEqual(resp3.missing_fields, [])


if __name__ == "__main__":
    unittest.main()
