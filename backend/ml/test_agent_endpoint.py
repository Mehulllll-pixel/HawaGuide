"""
Comprehensive Test Script for LangGraph StateGraph & POST /agent/recommend Endpoint
Testing Tier 3 (stays elevated) and Tier 2 (crosses into better band in 3 hours)
"""

import sys
import io
import json
from pathlib import Path

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def run_scenario(title: str, payload: dict):
    print("=" * 95)
    print(f"   TEST SCENARIO: {title}")
    print("=" * 95)
    print("\nUser Input Profile:")
    for k, v in payload.items():
        print(f"  • {k}: {v}")

    res = client.post("/agent/recommend", json=payload)
    if res.status_code != 200:
        print(f"Error {res.status_code}: {res.text}")
        return

    data = res.json()
    
    print("\n" + "-" * 95)
    print("  NODE-BY-NODE STATE TRACE (5 Graph Nodes)")
    print("-" * 95)
    for i, step in enumerate(data.get("trace", []), start=1):
        print(f"\n[Node {i}/5] >> {step['node'].upper()} <<")
        print(f"  Description: {step['description']}")
        print("  State Snapshot:")
        for k, v in step['data'].items():
            if isinstance(v, (list, dict)):
                val_str = json.dumps(v, indent=4)
                indented = "\n".join("      " + line for line in val_str.split("\n"))
                print(f"    • {k}:\n{indented}")
            else:
                print(f"    • {k}: {v}")

    print("\n" + "=" * 95)
    print("  FINAL AGENT RECOMMENDATION & SYNTHESIS")
    print("=" * 95)
    print(f"Recommended Park                 : {data.get('best_park', {}).get('name')} ({data.get('best_park', {}).get('distance_km')} km away)")
    print(f"Best Time Window                 : {data.get('best_time_window')}")
    print(f"Start Location Personalized PEVI : {data.get('start_location_personalized_pevi'):.2f}")
    print(f"Recommended Park Pers. PEVI      : {data.get('recommended_park_personalized_pevi'):.2f} ({data.get('recommended_park_risk_band')})")
    print(f"Compound Multiplier              : {data.get('multipliers', {}).get('total_compound_multiplier')}x")
    print(f"\nAgent Guidance Text:\n\"{data.get('recommendation')}\"")
    print(f"\nDisclaimer:\n\"{data.get('disclaimer')}\"")
    print("=" * 95 + "\n\n")


# Scenario 1: Elderly, Asthma, Moderate, 2.0h -> TIER 3 (Extreme throughout 6h)
scenario_1_tier3 = {
    "lat": 28.6328,
    "lon": 77.2197,
    "age_group": "elderly",
    "conditions": ["asthma"],
    "smoker": False,
    "planned_activity": "moderate",
    "duration_hours": 2.0,
    "alpha": 0.6
}

# Scenario 2: Adult, Asthma, Moderate, 1.5h -> TIER 2 (High Band 3 now -> Moderate Band 2 in 3h)
scenario_2_tier2 = {
    "lat": 28.6328,
    "lon": 77.2197,
    "age_group": "adult",
    "conditions": ["asthma"],
    "smoker": False,
    "planned_activity": "moderate",
    "duration_hours": 1.5,
    "alpha": 0.6
}

run_scenario("SCENARIO 1 (TIER 3: Stays Extreme/High for 6 hours)", scenario_1_tier3)
run_scenario("SCENARIO 2 (TIER 2: Genuine Band Crossing from High to Moderate in 3 hours)", scenario_2_tier2)

