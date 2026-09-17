"""
===================================================================================================
Test: Genuine LLM Semantic Extraction (No Literal Regex Keywords)
===================================================================================================

Target Bug / Quality Gate:
--------------------------
Ensure slot extraction uses genuine Gemini LLM semantic comprehension rather than superficial
keyword regex matching. When given phrasing without standard keywords (e.g., "getting on in years"
instead of "elderly", "breathing trouble" instead of "asthma", "strolling" instead of "moderate"),
the extractor must correctly map semantic intent to valid schema enums.

Test Queries:
-------------
1. "My mother is getting on in years and has persistent breathing trouble. She wants to go for a 45-minute stroll around Lodhi Garden."
   - age_group -> "elderly" (from "getting on in years")
   - conditions -> ["respiratory"] (from "breathing trouble")
   - planned_activity -> "rest" or "moderate" (from "stroll")
   - duration_hours -> 0.75 (from "45-minute")
   - location -> resolved coordinates for Lodhi Garden

2. "Taking my 7-year-old kid for an intense soccer practice for an hour near Connaught Place. No health issues."
   - age_group -> "child" (from "7-year-old kid")
   - planned_activity -> "vigorous" (from "intense soccer practice")
   - duration_hours -> 1.0 (from "an hour")
   - conditions -> [] (from "No health issues")
===================================================================================================
"""

import os
import sys
import unittest
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
for p in [PROJECT_ROOT / "backend" / ".env", PROJECT_ROOT / ".env"]:
    if p.exists():
        load_dotenv(p)
        break

from backend.app.main import _extract_fields_via_gemini, _extract_fields_from_text


class TestAgentGenuineExtraction(unittest.TestCase):

    def setUp(self):
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            self.skipTest("Gemini API key not configured; skipping live LLM extraction test.")

    def test_semantic_extraction_without_literal_keywords(self):
        """
        Query 1: 'getting on in years' (elderly) + 'breathing trouble' (respiratory) + 'stroll' (rest/moderate)
        """
        query = (
            "My mother is getting on in years and has severe breathing trouble. "
            "She wants to go for a 45 minute stroll around Lodhi Garden."
        )

        try:
            extracted = _extract_fields_via_gemini(query, self.api_key)
        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e) or "503" in str(e) or "UNAVAILABLE" in str(e):
                self.skipTest(f"Gemini API rate limit or service overload: {e}")
            raise

        self.assertEqual(
            extracted.get("age_group"), "elderly",
            f"Expected 'elderly' from 'getting on in years', got: {extracted.get('age_group')}"
        )
        self.assertTrue(
            "respiratory" in extracted.get("conditions", []) or "asthma" in extracted.get("conditions", []),
            f"Expected 'respiratory' or 'asthma' from 'breathing trouble', got: {extracted.get('conditions')}"
        )
        self.assertIn(
            extracted.get("planned_activity"), ["rest", "moderate"],
            f"Expected 'rest' or 'moderate' from 'stroll', got: {extracted.get('planned_activity')}"
        )
        self.assertAlmostEqual(
            extracted.get("duration_hours", 0.0), 0.75, delta=0.1,
            msg=f"Expected ~0.75 hours from '45 minute', got: {extracted.get('duration_hours')}"
        )
        # Location verification (either geocoded lat/lon or extracted location string)
        has_location = ("lat" in extracted and "lon" in extracted) or (
            "Lodhi Garden" in extracted.get("_location_unresolved", "") or "Lodhi Garden" in extracted.get("_location_name", "")
        )
        self.assertTrue(has_location, f"Expected Lodhi Garden location extracted, got: {extracted}")

    def test_child_vigorous_extraction_without_literal_keywords(self):
        """
        Query 2: '7-year-old kid' (child) + 'intense soccer practice' (vigorous) + 'an hour' (1.0h) + 'no health issues' ([])
        """
        query = (
            "Taking my 7-year-old kid for an intense soccer practice for an hour near Connaught Place. "
            "We have no health issues and don't smoke."
        )

        try:
            extracted = _extract_fields_via_gemini(query, self.api_key)
        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e) or "503" in str(e) or "UNAVAILABLE" in str(e):
                self.skipTest(f"Gemini API rate limit or service overload: {e}")
            raise

        self.assertEqual(extracted.get("age_group"), "child")
        self.assertEqual(extracted.get("planned_activity"), "vigorous")
        self.assertAlmostEqual(extracted.get("duration_hours", 0.0), 1.0, delta=0.1)
        self.assertEqual(extracted.get("conditions"), [])
        self.assertEqual(extracted.get("smoker"), False)

        has_location = ("lat" in extracted and "lon" in extracted) or (
            "Connaught Place" in extracted.get("_location_unresolved", "") or "Connaught Place" in extracted.get("_location_name", "")
        )
        self.assertTrue(has_location, f"Expected Connaught Place location extracted, got: {extracted}")


if __name__ == "__main__":
    unittest.main()
