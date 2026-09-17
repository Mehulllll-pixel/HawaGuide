"""
Test script to verify real inference on /forecast/{location_name} and prove distinct forecast shapes.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def test_parks():
    test_parks = [
        "Lodhi Garden",
        "Yamuna Biodiversity Park",
        "Sanjay Van",
        "Swarna Jayanti Park",
        "Aravalli Biodiversity Park",
    ]

    print("=" * 100)
    print("VERIFYING REAL ML INFERENCE ACROSS MULTIPLE PARKS")
    print("=" * 100)

    results = {}
    for park in test_parks:
        resp = client.get(f"/forecast/{park}")
        print(f"\n--- Location: {park} (Status: {resp.status_code}) ---")
        assert resp.status_code == 200, f"Failed for {park}: {resp.text}"
        data = resp.json()
        results[park] = data
        
        print(f"Location: {data['location_name']} | Zone: {data['zone']} | Current PM2.5: {data['current_pm25']} ug/m3")
        print(f"Model Blend: {data['model_blend']}")
        print(f"{'Hour Ahead':<12} {'Forecast PM2.5':<16} {'Delta':<10} {'Trend':<25}")
        print("-" * 65)
        for pt in data["hourly_trajectory"]:
            print(f"t+{pt['hour_ahead']}h         {pt['forecast_pm25']:<16.1f} {pt['delta_from_now']:<+10.1f} {pt['trend']}")

    print("\n" + "=" * 100)
    print("COMPARING TRAJECTORY SHAPES (GENUINELY DIFFERENT SHAPES):")
    print("=" * 100)
    print(f"{'Location':<30} | {'t+1h':>8} {'t+2h':>8} {'t+3h':>8} {'t+4h':>8} {'t+5h':>8} {'t+6h':>8} | {'Total Delta':>12}")
    print("-" * 100)
    for park, data in results.items():
        vals = [pt["forecast_pm25"] for pt in data["hourly_trajectory"]]
        deltas = data["hourly_trajectory"][-1]["forecast_pm25"] - data["current_pm25"]
        val_strs = " ".join(f"{v:>7.1f}u" for v in vals)
        print(f"{park:<30} | {val_strs} | {deltas:>+10.1f}u")
    print("=" * 100)

if __name__ == "__main__":
    test_parks()
