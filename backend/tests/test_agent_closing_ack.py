"""
Test: Casual Acknowledgment / Closing Handling

Verifies that sending casual closing or acknowledgment messages ("Thank you", "thanks", "ok", "got it", "bye"):
1. Does NOT re-trigger or restart the sequential clarification flow.
2. Does NOT ask for duration, location, or any other field.
3. Returns a polite, warm closing reply with status="complete" and missing_fields=[].
"""

import unittest
import uuid
from backend.app.main import conversational_ask, AgentAskRequest, _SESSIONS


class TestAgentClosingAcknowledgment(unittest.TestCase):

    def setUp(self):
        self.session_id = f"test-closing-{uuid.uuid4()}"
        _SESSIONS.pop(self.session_id, None)

    def tearDown(self):
        _SESSIONS.pop(self.session_id, None)

    def test_thank_you_after_recommendation_does_not_retrigger_flow(self):
        # Step 1: Execute complete recommendation flow
        saved_profile = {
            "age_group": "adult",
            "conditions": [],
            "smoker": False,
            "planned_activity": "moderate",
        }

        # Turn 1: Start with saved profile -> asks for duration
        resp1 = conversational_ask(AgentAskRequest(
            session_id=self.session_id,
            message="Find me a park",
            profile=saved_profile,
        ))
        self.assertEqual(resp1.status, "clarifying")
        self.assertEqual(resp1.missing_fields[0], "duration_hours")

        # Turn 2: Provide duration -> asks for location
        resp2 = conversational_ask(AgentAskRequest(
            session_id=self.session_id,
            message="30 minutes",
            profile=saved_profile,
        ))
        self.assertEqual(resp2.status, "clarifying")
        self.assertEqual(resp2.missing_fields[0], "location")

        # Turn 3: Provide location -> completes recommendation
        resp3 = conversational_ask(AgentAskRequest(
            session_id=self.session_id,
            message="Lodhi Garden",
            profile=saved_profile,
        ))
        self.assertEqual(resp3.status, "complete")
        self.assertIsNotNone(resp3.recommendation)

        # Step 2: User sends "Thank you" as the next message
        resp4 = conversational_ask(AgentAskRequest(
            session_id=self.session_id,
            message="Thank you",
            profile=saved_profile,
        ))

        # Must be polite closing reply, NOT a clarification question
        self.assertEqual(resp4.status, "complete")
        self.assertEqual(resp4.missing_fields, [])
        self.assertIn("welcome", resp4.message.lower())
        self.assertNotIn("how long", resp4.message.lower())
        self.assertNotIn("duration", resp4.message.lower())
        self.assertNotIn("location", resp4.message.lower())
        self.assertNotIn("age", resp4.message.lower())

    def test_various_acknowledgment_phrases(self):
        phrases = [
            "thanks",
            "Thanks!",
            "ok",
            "okay",
            "got it",
            "Got it, thanks!",
            "bye",
            "goodbye",
            "cool, thanks",
            "great, appreciate it!",
        ]
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                sess = f"test-ack-{uuid.uuid4()}"
                resp = conversational_ask(AgentAskRequest(
                    session_id=sess,
                    message=phrase,
                    profile={"age_group": "adult", "conditions": [], "smoker": False, "planned_activity": "moderate"},
                ))
                self.assertEqual(resp.status, "complete")
                self.assertEqual(resp.missing_fields, [])
                self.assertIn("welcome", resp.message.lower())


if __name__ == "__main__":
    unittest.main()
