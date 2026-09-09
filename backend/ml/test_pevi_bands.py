"""
===================================================================================================
Unit & Integration Tests: Base PEVI Band Classification Logic & /locations Verification
===================================================================================================
"""

import sys
import io
from pathlib import Path

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from fastapi.testclient import TestClient
from backend.ml.optimizer import get_base_pevi_band, get_personalized_risk_band
from backend.app.main import app

# ─── 1. Unit Tests for get_base_pevi_band ───────────────────────────────────────

def test_base_pevi_band_classification():
    """
    Verifies that get_base_pevi_band assigns the exact documented base PEVI quartile thresholds:
      - Low (Band 1):      PEVI <= 4.13
      - Moderate (Band 2): 4.13 < PEVI <= 4.81
      - High (Band 3):     4.81 < PEVI <= 5.65
      - Highest (Band 4):  PEVI > 5.65
    """
    test_cases = [
        # Standard representative points
        (3.50, "Low (Band 1)"),
        (4.50, "Moderate (Band 2)"),
        (5.00, "High (Band 3)"),
        (6.50, "Highest (Band 4)"),
        
        # Specific failing / critical values reported
        (6.23, "Highest (Band 4)"),   # Amrit Udyan
        (4.84, "High (Band 3)"),      # Aravalli Biodiversity Park Vasant Kunj
        (4.12, "Low (Band 1)"),       # Aravalli Biodiversity Park Gurugram
        
        # Exact boundary conditions
        (4.13, "Low (Band 1)"),
        (4.1301, "Moderate (Band 2)"),
        (4.81, "Moderate (Band 2)"),
        (4.8101, "High (Band 3)"),
        (5.65, "High (Band 3)"),
        (5.6501, "Highest (Band 4)")
    ]

    for val, expected_band in test_cases:
        actual_band = get_base_pevi_band(val)
        assert actual_band == expected_band, (
            f"Failed for Base PEVI={val}: Expected '{expected_band}', got '{actual_band}'"
        )
        print(f"  [PASS] Base PEVI {val:>6.2f} -> {actual_band}")


# ─── 2. Integration Test with Live /locations Endpoint ──────────────────────────

def test_live_locations_bands():
    """
    Queries /locations and asserts that Amrit Udyan, Aravalli Biodiversity Park Vasant Kunj,
    and Aravalli Biodiversity Park Gurugram have their expected risk bands.
    """
    client = TestClient(app)
    response = client.get("/locations")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"

    locations_map = {loc["name"]: loc for loc in data["locations"]}

    # 1. Amrit Udyan
    amrit_key = [k for k in locations_map if "Amrit Udyan" in k][0]
    amrit = locations_map[amrit_key]
    print(f"\nLive Park: {amrit['name']}")
    print(f"  PEVI: {amrit['current_pevi']}")
    print(f"  Band: {amrit['personalized_risk_band']}")
    assert amrit["personalized_risk_band"] == "Highest (Band 4)", (
        f"Amrit Udyan expected 'Highest (Band 4)', got '{amrit['personalized_risk_band']}'"
    )

    # 2. Aravalli Biodiversity Park (Vasant Kunj)
    vk_key = [k for k in locations_map if "Vasant Kunj" in k][0]
    vk = locations_map[vk_key]
    print(f"\nLive Park: {vk['name']}")
    print(f"  PEVI: {vk['current_pevi']}")
    print(f"  Band: {vk['personalized_risk_band']}")
    assert vk["personalized_risk_band"] == "High (Band 3)", (
        f"Aravalli Vasant Kunj expected 'High (Band 3)', got '{vk['personalized_risk_band']}'"
    )

    # 3. Aravalli Biodiversity Park (Gurugram)
    ggn_key = [k for k in locations_map if "Gurugram" in k][0]
    ggn = locations_map[ggn_key]
    print(f"\nLive Park: {ggn['name']}")
    print(f"  PEVI: {ggn['current_pevi']}")
    print(f"  Band: {ggn['personalized_risk_band']}")
    assert ggn["personalized_risk_band"] == "Low (Band 1)", (
        f"Aravalli Gurugram expected 'Low (Band 1)', got '{ggn['personalized_risk_band']}'"
    )


if __name__ == "__main__":
    print("=" * 75)
    print("RUNNING UNIT TESTS FOR BASE PEVI BAND ASSIGNMENT")
    print("=" * 75)
    test_base_pevi_band_classification()
    
    print("\n" + "=" * 75)
    print("RUNNING INTEGRATION TEST FOR /locations ENDPOINT")
    print("=" * 75)
    test_live_locations_bands()
    print("\n[+] All PEVI band classification tests passed successfully!")
