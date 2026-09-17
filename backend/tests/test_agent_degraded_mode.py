"""
===================================================================================================
Test: Agent Degraded Mode Handling (Simulated LLM API Failure)
===================================================================================================

Target Failure Mode:
---------------------
When the Google Gemini API fails (e.g. 503 service outage, 429 quota exhaustion, or invalid network),
the system must NOT:
- Crash with an unhandled 500 internal server error.
- Silently guess fallback values or invent default slots.

Instead, the system must gracefully degrade:
1. `extraction_degraded` is set to `True` in the API response.
2. `status` is set to `'clarifying'`.
3. The clarification message explicitly acknowledges trouble understanding free-text and asks
   the user for the required fields directly.
4. The endpoint returns a valid 200 HTTP response.
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


class TestAgentDegradedMode(unittest.TestCase):

    def setUp(self):
        self.session_id = f"test-degraded-{uuid.uuid4()}"

    def tearDown(self):
        _SESSIONS.pop(self.session_id, None)

    @patch("backend.app.main._extract_fields_via_gemini")
    def test_gemini_failure_triggers_degraded_mode_response(self, mock_gemini):
        """
        Simulate Gemini raising a 503 Unavailable exception.
        Confirm conversational_ask returns extraction_degraded=True and clarifying question.
        """
        mock_gemini.side_effect = Exception("503 Service Unavailable: Google GenAI backend overloaded")

        req = AgentAskRequest(
            session_id=self.session_id,
            message="I want to go for a run in Lodhi Garden, I am 30 years old with no medical issues."
        )

        resp = conversational_ask(req)

        # 1. extraction_degraded must be True
        self.assertTrue(resp.extraction_degraded, "Response must flag extraction_degraded=True")

        # 2. status must be clarifying
        self.assertEqual(resp.status, "clarifying")

        # 3. Message must politely explain free-text trouble
        self.assertIn("having trouble understanding free-text", resp.message)

        # 4. Recommendation must be None
        self.assertIsNone(resp.recommendation)

        # 5. Missing fields must list required slots
        self.assertGreater(len(resp.missing_fields), 0)


if __name__ == "__main__":
    unittest.main()
