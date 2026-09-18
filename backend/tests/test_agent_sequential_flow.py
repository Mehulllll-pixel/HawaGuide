"""
===================================================================================================
Test: Agent Sequential Clarification Flow, Age Transparency & Invalid Answer Handling
===================================================================================================
"""

import sys
import unittest
from unittest.mock import patch
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.main import (
    conversational_ask,
    AgentAskRequest,
    _SESSIONS,
    map_age_to_group,
    _parse_direct_fields
)


class TestAgentSequentialFlow(unittest.TestCase):

    def setUp(self):
        self.session_id = f"test-seq-{uuid.uuid4()}"

    def tearDown(self):
        _SESSIONS.pop(self.session_id, None)

    def test_full_sequential_flow_from_empty_query(self):
        """
        User provides NOTHING in Turn 1 ('is it safe to go outside').
        The agent must ask ONE question at a time in the exact fixed order:
        age -> health condition -> smoker status -> activity level -> duration -> location.
        """
        # --- TURN 1: Empty intent ---
        req1 = AgentAskRequest(session_id=self.session_id, message="is it safe to go outside")
        resp1 = conversational_ask(req1)

        self.assertEqual(resp1.status, "clarifying")
        self.assertEqual(resp1.missing_fields[0], "age_group")
        self.assertIn("What's your age?", resp1.message)
        self.assertIn("Under 18 = child, 18-64 = adult, 65+ = elderly", resp1.message)
        self.assertIsNone(resp1.recommendation)

        # --- TURN 2: Raw number age '34' ---
        req2 = AgentAskRequest(session_id=self.session_id, message="34")
        resp2 = conversational_ask(req2)

        self.assertEqual(resp2.status, "clarifying")
        self.assertEqual(resp2.missing_fields[0], "conditions")
        # Explicit age confirmation prepended to next question
        self.assertTrue(resp2.message.startswith("Got it, categorizing you as adult (18-64)."))
        self.assertIn("Do you have any of these health conditions: asthma, cardiac, or none?", resp2.message)

        # --- TURN 3: Health condition 'none' ---
        req3 = AgentAskRequest(session_id=self.session_id, message="none")
        resp3 = conversational_ask(req3)

        self.assertEqual(resp3.status, "clarifying")
        self.assertEqual(resp3.missing_fields[0], "smoker")
        self.assertIn("Do you smoke tobacco?", resp3.message)

        # --- TURN 4: Smoker status 'no' ---
        req4 = AgentAskRequest(session_id=self.session_id, message="no")
        resp4 = conversational_ask(req4)

        self.assertEqual(resp4.status, "clarifying")
        self.assertEqual(resp4.missing_fields[0], "planned_activity")
        self.assertIn("What activity level are you planning: rest, moderate, or vigorous?", resp4.message)

        # --- TURN 5: Activity level 'moderate' ---
        req5 = AgentAskRequest(session_id=self.session_id, message="moderate")
        resp5 = conversational_ask(req5)

        self.assertEqual(resp5.status, "clarifying")
        self.assertEqual(resp5.missing_fields[0], "duration_hours")
        self.assertIn("How long do you plan to be outside?", resp5.message)

        # --- TURN 6: Duration '30 minutes' ---
        req6 = AgentAskRequest(session_id=self.session_id, message="30 minutes")
        resp6 = conversational_ask(req6)

        self.assertEqual(resp6.status, "clarifying")
        self.assertEqual(resp6.missing_fields[0], "location")
        self.assertIn("Where are you located in Delhi NCR?", resp6.message)

        # --- TURN 7: Location 'Lodhi Garden' ---
        mock_rec = {
            "park_name": "Lodhi Garden",
            "aqi": 180,
            "pevi": 195,
            "safety_band": "UNHEALTHY",
            "activity": "moderate",
            "duration_hours": 0.5,
            "conditions": ["none"],
            "smoker": False,
            "age_group": "adult",
            "multipliers": {"age_multiplier": 1.0, "smoker_multiplier": 1.0, "conditions_multiplier": 1.0},
            "recommendation": "Moderate outdoor activity should be limited at Lodhi Garden."
        }
        with patch("backend.app.main.run_agent_recommendation", return_value=mock_rec):
            req7 = AgentAskRequest(session_id=self.session_id, message="Lodhi Garden")
            resp7 = conversational_ask(req7)

        # All fields collected -> full recommendation
        self.assertEqual(resp7.status, "complete")
        self.assertEqual(resp7.missing_fields, [])
        self.assertIsNotNone(resp7.recommendation)
        self.assertIn("recommendation", resp7.recommendation)
        self.assertEqual(resp7.recommendation["multipliers"]["age_multiplier"], 1.0)
        self.assertEqual(resp7.recommendation["multipliers"]["smoker_multiplier"], 1.0)

    def test_age_transparency_brackets(self):
        """
        Verify age mapping and explicit confirmation for child, adult, and elderly.
        """
        # Child: under 18
        sess_child = f"test-child-{uuid.uuid4()}"
        conversational_ask(AgentAskRequest(session_id=sess_child, message="help"))
        resp_child = conversational_ask(AgentAskRequest(session_id=sess_child, message="10"))
        self.assertIn("Got it, categorizing you as child (under 18).", resp_child.message)
        _SESSIONS.pop(sess_child, None)

        # Elderly: 65+
        sess_elderly = f"test-elderly-{uuid.uuid4()}"
        conversational_ask(AgentAskRequest(session_id=sess_elderly, message="help"))
        resp_elderly = conversational_ask(AgentAskRequest(session_id=sess_elderly, message="72"))
        self.assertIn("Got it, categorizing you as elderly (65+).", resp_elderly.message)
        _SESSIONS.pop(sess_elderly, None)

    def test_invalid_answer_reasks_without_guessing_default(self):
        """
        When user gives an ambiguous / unparseable answer to a sequential question,
        the system must NOT guess a default; it must re-ask with a clarifying note.
        """
        # Advance to smoker question
        conversational_ask(AgentAskRequest(session_id=self.session_id, message="is it safe?"))
        conversational_ask(AgentAskRequest(session_id=self.session_id, message="25"))
        conversational_ask(AgentAskRequest(session_id=self.session_id, message="none"))

        # Check we are at smoker question
        stored = _SESSIONS.get(self.session_id, {})
        self.assertEqual(stored.get("_last_asked_field"), "smoker")

        # Now send ambiguous reply 'maybe' / 'sometimes'
        resp_ambig = conversational_ask(AgentAskRequest(session_id=self.session_id, message="maybe"))

        # Must NOT advance to activity! Must remain on smoker with re-ask note
        self.assertEqual(resp_ambig.status, "clarifying")
        self.assertEqual(resp_ambig.missing_fields[0], "smoker")
        self.assertIn("I didn't quite catch that", resp_ambig.message)
        self.assertIn("please answer yes or no: do you smoke tobacco?", resp_ambig.message)

        # Smoker must still NOT be in session state
        stored_after = _SESSIONS.get(self.session_id, {})
        self.assertNotIn("smoker", stored_after)

    def test_single_turn_full_extraction_bypasses_sequential_flow(self):
        """
        When user sends complete free-text with all details in Turn 1,
        the agent skips sequential flow completely and gives immediate recommendation.
        """
        mock_rec = {
            "park_name": "Lodhi Garden",
            "aqi": 180,
            "pevi": 195,
            "safety_band": "UNHEALTHY",
            "activity": "moderate",
            "duration_hours": 1.0,
            "conditions": ["none"],
            "smoker": False,
            "age_group": "adult",
            "recommendation": "Moderate outdoor activity at Lodhi Garden is acceptable."
        }
        with patch("backend.app.main.run_agent_recommendation", return_value=mock_rec):
            req = AgentAskRequest(
                session_id=self.session_id,
                message="I am a 34-year-old adult, non-smoker, no health conditions, planning a 1 hour moderate walk at Lodhi Garden."
            )
            resp = conversational_ask(req)

        self.assertEqual(resp.status, "complete")
        self.assertEqual(resp.missing_fields, [])
        self.assertIsNotNone(resp.recommendation)
        self.assertIn("Lodhi Garden", resp.message)

    def test_age_boundary_bucketing(self):
        """Test boundary conditions for age mapping."""
        self.assertEqual(map_age_to_group(17), "child")
        self.assertEqual(map_age_to_group(18), "adult")
        self.assertEqual(map_age_to_group(64), "adult")
        self.assertEqual(map_age_to_group(65), "elderly")
        self.assertEqual(map_age_to_group("12 years old"), "child")
        self.assertEqual(map_age_to_group("45"), "adult")
        self.assertEqual(map_age_to_group("75"), "elderly")
        self.assertEqual(map_age_to_group("senior"), "elderly")
        self.assertEqual(map_age_to_group("kid"), "child")

    def test_duration_parsing(self):
        """Test parsing of common duration phrases."""
        p1 = _parse_direct_fields("an hour")
        self.assertEqual(p1.get("duration_hours"), 1.0)

        p2 = _parse_direct_fields("30 minutes")
        self.assertEqual(p2.get("duration_hours"), 0.5)

        p3 = _parse_direct_fields("45 mins")
        self.assertEqual(p3.get("duration_hours"), 0.75)

        p4 = _parse_direct_fields("2 hours")
        self.assertEqual(p4.get("duration_hours"), 2.0)

        p5 = _parse_direct_fields("1.5 hours")
        self.assertEqual(p5.get("duration_hours"), 1.5)


if __name__ == "__main__":
    unittest.main()
