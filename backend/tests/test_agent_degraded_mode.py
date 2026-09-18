"""
===================================================================================================
Test: Agent Degraded Mode Handling (Simulated LLM API Failure & Missing Key)
===================================================================================================

Target Failure Modes:
---------------------
When the Google Gemini API fails (e.g. 503 service outage, 429 quota exhaustion) or when no
GEMINI_API_KEY is configured in the environment, the system must NOT:
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

import os
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

    @patch.dict(os.environ, {"GROQ_API_KEY": "dummy_groq_key", "GEMINI_API_KEY": "dummy_gemini_key"}, clear=False)
    @patch("backend.app.main._extract_fields_via_llm")
    def test_llm_failure_triggers_degraded_mode_response(self, mock_llm):
        """
        Simulate LLM raising an exception (service outage or rate limits).
        Confirm conversational_ask returns extraction_degraded=True and clarifying question.
        Works in CI with no real API key required.
        """
        mock_llm.side_effect = Exception("503 Service Unavailable: Provider backend overloaded")

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

    @patch.dict(os.environ, {"GROQ_API_KEY": "", "GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}, clear=False)
    @patch("backend.app.main._extract_fields_via_llm")
    def test_missing_api_key_triggers_degraded_mode_response(self, mock_llm):
        """
        Simulate runtime environment with no API keys configured.
        Confirm conversational_ask returns extraction_degraded=True and clarifying question.
        """
        mock_llm.side_effect = ValueError("Neither GROQ_API_KEY nor GEMINI_API_KEY is configured.")

        req = AgentAskRequest(
            session_id=self.session_id,
            message="I want to go for a walk in Sanjay Van."
        )

        resp = conversational_ask(req)

        self.assertTrue(resp.extraction_degraded, "Response must flag extraction_degraded=True when API key is missing")
        self.assertEqual(resp.status, "clarifying")
        self.assertIn("having trouble understanding free-text", resp.message)
        self.assertIsNone(resp.recommendation)
        self.assertGreater(len(resp.missing_fields), 0)


if __name__ == "__main__":
    unittest.main()
