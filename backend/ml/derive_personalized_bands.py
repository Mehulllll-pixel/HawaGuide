import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
from backend.ml.optimizer import optimize_parks, calculate_personalized_pevi, DELHI_NCR_PARKS, get_db_connection

# 1. Exact decimal check for Scenario 1
print("=" * 90)
print("1. PRECISION CHECK: MANSOVAR PARK vs OKHLA BIRD SANCTUARY (SCENARIO 1)")
print("=" * 90)

cp_lat, cp_lon = 28.6328, 77.2197
ranked_1 = optimize_parks(
    start_lat=cp_lat,
    start_lon=cp_lon,
    age_group="elderly",
    condition="respiratory",
    duration_hours=2.0,
    alpha=0.7
)

for p in ranked_1[:5]:
    print(f"Rank {p['rank']}: {p['name']}")
    print(f"   Distance:      {p['distance_km']:.6f} km ({p['distance_meters']:.3f} m)")
    print(f"   Base PEVI:     {p['base_pevi']:.6f}")
    print(f"   Pers PEVI:     {p['personalized_pevi']:.6f}")
    print(f"   Norm Risk:     {p['norm_risk']:.8f}")
    print(f"   Norm Distance: {p['norm_distance']:.8f}")
    print(f"   Score:         {p['score']:.8f}")
    print("-" * 60)

# 2. Personalized PEVI distribution across personas
print("\n" + "=" * 90)
print("2. DERIVING PERSONALIZED PEVI RISK BANDS ACROSS 40 PARKS & REPRESENTATIVE PERSONAS")
print("=" * 90)

conn = get_db_connection()
with conn.cursor() as cur:
    cur.execute("""
        WITH latest_pevi AS (
            SELECT DISTINCT ON (location_name) location_name, pevi_value
            FROM pevi_scores
            ORDER BY location_name, timestamp DESC
        )
        SELECT p.name, COALESCE(lp.pevi_value, 5.0) as base_pevi
        FROM parks p LEFT JOIN latest_pevi lp ON p.name = lp.location_name
        ORDER BY p.name;
    """)
    base_pevis = [r[1] for r in cur.fetchall()]
conn.close()

base_arr = np.array(base_pevis)
print(f"Base PEVI (40 parks): Min={base_arr.min():.2f}, Q1={np.percentile(base_arr, 25):.2f}, Median={np.median(base_arr):.2f}, Mean={base_arr.mean():.2f}, Q3={np.percentile(base_arr, 75):.2f}, Max={base_arr.max():.2f}")

personas = [
    ("Adult Healthy 1h (Standard Adult)", "adult", "healthy", 1.0),
    ("Child Healthy 1h (Active Child)", "child", "healthy", 1.0),
    ("Adult Respiratory 1h (Asthmatic Adult)", "adult", "respiratory", 1.0),
    ("Elderly Respiratory 2h (High Sensitivity Persona)", "elderly", "respiratory", 2.0),
]

all_pers_scores = []
for label, age, cond, dur in personas:
    scores = [calculate_personalized_pevi(b, age, cond, dur) for b in base_arr]
    all_pers_scores.extend(scores)
    s_arr = np.array(scores)
    print(f"\n{label}:")
    print(f"   Total Multiplier: {calculate_personalized_pevi(1.0, age, cond, dur):.3f}x")
    print(f"   Min={s_arr.min():.2f}, Q1={np.percentile(s_arr, 25):.2f}, Median={np.median(s_arr):.2f}, Mean={s_arr.mean():.2f}, Q3={np.percentile(s_arr, 75):.2f}, Max={s_arr.max():.2f}")

all_pers_arr = np.array(all_pers_scores)
print("\n" + "=" * 90)
print("POOLED PERSONALIZED PEVI DISTRIBUTION (Across all representative usage profiles):")
print(f"   Pooled N = {len(all_pers_arr)}")
print(f"   Min    = {all_pers_arr.min():.2f}")
print(f"   Q1     = {np.percentile(all_pers_arr, 25):.2f}")
print(f"   Median = {np.median(all_pers_arr):.2f}")
print(f"   Mean   = {all_pers_arr.mean():.2f}")
print(f"   Q3     = {np.percentile(all_pers_arr, 75):.2f}")
print(f"   Max    = {all_pers_arr.max():.2f}")
