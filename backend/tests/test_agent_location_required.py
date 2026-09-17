"""
===================================================================================================
Test: Location Required Guardrail (No Guessed Defaults)
===================================================================================================

Target Bug / Safety Requirement:
---------------------------------
Confirm that when a user provides all profile fields (age, conditions, smoker, activity, duration)
but OMITS their location, the conversational agent returns a clarifying question explicitly asking
for their location, and NEVER silently guesses a default location (e.g. Connaught Place / Central Delhi).

Assertions:
1. Status is 'clarifying'.
2. 'location' is in 'missing_fields'.
3. Recommendation payload is None.
4. Response message asks for location.
5. No fake coordinates (lat/lon) are populated in session state.
===================================================================================================
"""

import sys
import unittest
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.main import conversational_ask, AgentAskRequest, _SESSIONS


class TestAgentLocationRequired(unittest.TestCase):

    def setUp(self):
        self.session_id = f"test-loc-req-{uuid.uuid4()}"

    def tearDown(self):
        _SESSIONS.pop(self.session_id, None)

    def test_missing_location_prompts_clarification_no_default_guessing(self):
        """
        User provides age, asthma condition, non-smoker, 1 hour walk, but no location.
        The agent must ask for location and return status='clarifying'.
        """
        # Pre-populate non-location fields or send message without location
        req = AgentAskRequest(
            session_id=self.session_id,
            message="I am an adult with asthma, non-smoker, planning a 1 hour moderate walk. Is it safe?"
        )

        resp = conversational_ask(req)

        # Assert status is clarifying
        self.assertEqual(resp.status, "clarifying", "Must be 'clarifying' when location is missing")
        self.assertIn("location", resp.missing_fields, "Missing fields must include 'location'")
        self.assertIsNone(resp.recommendation, "Recommendation must be None when location is missing")

        # Assert message contains location question
        self.assertTrue(
            "location" in resp.message.lower() or "where" in resp.message.lower(),
            f"Clarifying message must ask for location. Got: {resp.message}"
        )

        # Assert session state does NOT contain lat/lon
        session_state = _SESSIONS.get(self.session_id, {})
        self.assertNotIn("lat", session_state, "Agent must not invent lat")
        self.assertNotIn("lon", session_state, "Agent must not invent lon")


if __name__ == "__main__":
    unittest.main()
