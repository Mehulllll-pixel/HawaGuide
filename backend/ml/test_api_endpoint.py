"""
Unit & Integration Test for FastAPI GET /optimize endpoint
"""

import sys
import io
from pathlib import Path

# Force UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

print("=" * 90)
print("TESTING FASTAPI /optimize ENDPOINT")
print("=" * 90)

# Test 1: Root endpoint
res_root = client.get("/")
print("GET / Response:", res_root.json())
assert res_root.status_code == 200

# Test 2: Target scenario requested by user:
# age_group=elderly, condition=respiratory, duration=2, alpha=0.7, start at Connaught Place (28.6328, 77.2197)
params = {
    "lat": 28.6328,
    "lon": 77.2197,
    "age_group": "elderly",
    "condition": "respiratory",
    "duration_hours": 2.0,
    "alpha": 0.7
}
res = client.get("/optimize", params=params)
assert res.status_code == 200, f"Error: {res.text}"
data = res.json()

print(f"\nQuery Status: {data['status']}")
print("Query Details:")
for k, v in data['query'].items():
    print(f"  • {k}: {v}")

print(f"\nTotal Ranked Parks Returned: {data['total_parks']}")
print("\nTop 10 Ranked Parks (Alpha = 0.7, 70% risk vs 30% distance):")
print(f"{'Rank':<5} {'Park Name':<32} {'Zone':<24} {'Dist (km)':>10} {'Base PEVI':>10} {'Pers PEVI':>10} {'Score':>8}")
print("-" * 105)
for p in data['recommendations'][:10]:
    print(f"{p['rank']:<5} {p['name']:<32} {p['zone']:<24} {p['distance_km']:>10.2f} {p['base_pevi']:>10.2f} {p['personalized_pevi']:>10.2f} {p['score']:>8.4f}")

# Test 3: Balanced scenario (child, asthma/respiratory, 1.5h, alpha=0.5, start at Hauz Khas 28.5492, 77.2000)
print("\n" + "=" * 90)
params_2 = {
    "lat": 28.5492,
    "lon": 77.2000,
    "age_group": "child",
    "condition": "respiratory",
    "duration_hours": 1.5,
    "alpha": 0.5
}
res_2 = client.get("/optimize", params=params_2)
assert res_2.status_code == 200
data_2 = res_2.json()

print("Query Details (Scenario 2):")
for k, v in data_2['query'].items():
    print(f"  • {k}: {v}")

print("\nTop 5 Ranked Parks (Child + Respiratory, Alpha=0.5):")
print(f"{'Rank':<5} {'Park Name':<32} {'Zone':<24} {'Dist (km)':>10} {'Base PEVI':>10} {'Pers PEVI':>10} {'Score':>8}")
print("-" * 105)
for p in data_2['recommendations'][:5]:
    print(f"{p['rank']:<5} {p['name']:<32} {p['zone']:<24} {p['distance_km']:>10.2f} {p['base_pevi']:>10.2f} {p['personalized_pevi']:>10.2f} {p['score']:>8.4f}")

print("\n[+] All endpoint tests passed successfully!")
