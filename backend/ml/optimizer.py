"""
===================================================================================================
HawaGuide — Personalized PEVI & Multi-Objective Spatial Park Location Optimizer
===================================================================================================

Module Overview:
----------------
This module implements the Personalized Exposure Vulnerability Index (PEVI) calculation
and multi-objective spatial location optimizer for urban green spaces across Delhi NCR.

1. Personalized PEVI Formulation:
----------------------------------
    Personalized_PEVI = Base_PEVI × age_multiplier × condition_multiplier × (1 + 0.15 × duration_hours)

    Multipliers:
    - age_multiplier:
        • 1.3 for "child" (<18) or "elderly" (65+)
        • 1.0 for "adult" (general healthy baseline)
    - condition_multiplier:
        • 1.5 for pre-existing "respiratory" (e.g. asthma, COPD) or "cardiac" conditions
        • 1.0 for "healthy" / none
    - duration_multiplier:
        • (1 + 0.15 × duration_hours) models cumulative inhaled dose during sustained outdoor activity.

    Epidemiological Rationale & Literature Basis:
    ---------------------------------------------
    These multipliers are informed by:
      1. US EPA "Particle Pollution Exposure" clinical and educational reference materials on sensitive
         subpopulations (children <18 with developing lungs and higher minute ventilation per body weight;
         older adults 65+ with reduced cardiovascular resilience; individuals with underlying cardiopulmonary disease).
      2. Multi-city time-series epidemiological literature on air pollution and asthma/cardiovascular hospital admissions
         (e.g., a Southwest China multi-city time-series study on ambient air pollution and elderly asthma hospitalization,
         PMC10859495; and related excess risk cohorts).
    
    IMPORTANT NOTE ON ATTRIBUTION:
      While conceptually grounded in EPA sensitive-group categorizations and published relative-risk ranges,
      these specific multiplier constants (1.3, 1.5, 0.15/hr) represent HawaGuide's own engineering and
      heuristic risk-weighting framework designed for comparative green space ranking. They are NOT directly
      published universal medical constants.

2. Multi-Objective Spatial Location Optimizer:
----------------------------------------------
    For a given user starting coordinate (lat, lon):
      1. Queries all 40 Delhi NCR parks.
      2. Computes true geodetic distance (meters / km) via PostGIS ST_Distance on geography(Point, 4326).
      3. Retrieves the current Base_PEVI from the pevi_scores table.
      4. Calculates Personalized_PEVI for each park.
      5. Min-max normalizes risk and distance across the 40 candidates to [0, 1]:
           norm_risk     = (risk - min_risk) / (max_risk - min_risk)
           norm_distance = (dist - min_dist) / (max_dist - min_dist)
      6. Computes composite multi-objective trade-off score:
           Score = α × norm_risk + (1 - α) × norm_distance    (where α ∈ [0, 1], lower score is better)
      7. Returns the 40 parks ranked by Score ascending (Rank 1 = optimal recommendation).
===================================================================================================
"""

import os
import sys
import math
import warnings
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Suppress pandas SQL UserWarning
warnings.filterwarnings("ignore", category=UserWarning)

# Load .env
BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

for candidate in [BACKEND_DIR / ".env", PROJECT_ROOT / ".env", Path(".env")]:
    if candidate.is_file():
        load_dotenv(dotenv_path=candidate)
        break
else:
    load_dotenv()

# 40 Real, Named Delhi NCR Parks & Green Spaces
DELHI_NCR_PARKS = [
    {"name": "Lodhi Garden", "lat": 28.5931, "lon": 77.2197, "zone": "Central Delhi"},
    {"name": "Sunder Nursery", "lat": 28.5915, "lon": 77.2435, "zone": "Nizamuddin / South East"},
    {"name": "Nehru Park", "lat": 28.5908, "lon": 77.1953, "zone": "Chanakyapuri"},
    {"name": "Deer Park", "lat": 28.5528, "lon": 77.1947, "zone": "Hauz Khas"},
    {"name": "District Park Hauz Khas", "lat": 28.5492, "lon": 77.1998, "zone": "Hauz Khas"},
    {"name": "Sanjay Van", "lat": 28.5273, "lon": 77.1722, "zone": "Qutub Institutional Area"},
    {"name": "Garden of Five Senses", "lat": 28.5134, "lon": 77.1983, "zone": "Said-ul-Ajaib / Saket"},
    {"name": "Buddha Jayanti Park", "lat": 28.6044, "lon": 77.1751, "zone": "Central Ridge"},
    {"name": "Central Park", "lat": 28.6328, "lon": 77.2197, "zone": "Connaught Place"},
    {"name": "India Gate Lawns", "lat": 28.6129, "lon": 77.2295, "zone": "Central Delhi"},
    {"name": "Amrit Udyan (Mughal Gardens)", "lat": 28.6143, "lon": 77.1988, "zone": "Rashtrapati Bhavan"},
    {"name": "Millennium Indraprastha Park", "lat": 28.6015, "lon": 77.2575, "zone": "Sarai Kale Khan"},
    {"name": "Japanese Park (Swarna Jayanti)", "lat": 28.7188, "lon": 77.1147, "zone": "Rohini Sector 10"},
    {"name": "Rohini District Park", "lat": 28.7115, "lon": 77.1256, "zone": "Rohini Sector 9"},
    {"name": "Yamuna Biodiversity Park", "lat": 28.7495, "lon": 77.2215, "zone": "Wazirabad"},
    {"name": "Aravalli Biodiversity Park (Vasant Kunj)", "lat": 28.5485, "lon": 77.1495, "zone": "Vasant Kunj"},
    {"name": "Aravalli Biodiversity Park (Gurugram)", "lat": 28.4812, "lon": 77.1008, "zone": "Gurugram"},
    {"name": "Leisure Valley Park", "lat": 28.4682, "lon": 77.0655, "zone": "Sector 29, Gurugram"},
    {"name": "Tau Devi Lal Biodiversity Park", "lat": 28.4357, "lon": 77.0862, "zone": "Sector 52, Gurugram"},
    {"name": "Biodiversity Park Okhla", "lat": 28.5612, "lon": 77.3065, "zone": "Kalindi Kunj"},
    {"name": "Okhla Bird Sanctuary", "lat": 28.5627, "lon": 77.3178, "zone": "Noida / Delhi Border"},
    {"name": "Meghdootam Park", "lat": 28.5862, "lon": 77.3621, "zone": "Sector 50, Noida"},
    {"name": "Noida Biodiversity Park", "lat": 28.5752, "lon": 77.3826, "zone": "Sector 91, Noida"},
    {"name": "Mansarovar Park", "lat": 28.5524, "lon": 77.3385, "zone": "Sector 38A, Noida"},
    {"name": "Smriti Van", "lat": 28.5833, "lon": 77.3512, "zone": "Sector 49, Noida"},
    {"name": "Asola Bhatti Wildlife Sanctuary", "lat": 28.4842, "lon": 77.2588, "zone": "Tughlakabad"},
    {"name": "Qudsia Bagh", "lat": 28.6678, "lon": 77.2285, "zone": "Civil Lines"},
    {"name": "Roshanara Bagh", "lat": 28.6698, "lon": 77.1994, "zone": "Shakti Nagar"},
    {"name": "Shalimar Bagh District Park", "lat": 28.7152, "lon": 77.1608, "zone": "North Delhi"},
    {"name": "Talkatora Gardens", "lat": 28.6202, "lon": 77.1957, "zone": "President's Estate"},
    {"name": "Mahavir Jayanti Park", "lat": 28.6185, "lon": 77.1824, "zone": "Ridge Road"},
    {"name": "National Rose Garden", "lat": 28.5574, "lon": 77.1825, "zone": "Chanakyapuri"},
    {"name": "Jahanpanah City Forest", "lat": 28.5322, "lon": 77.2384, "zone": "Alaknanda / GK"},
    {"name": "Sanjay Lake Park", "lat": 28.6182, "lon": 77.3061, "zone": "Mayur Vihar"},
    {"name": "Swarna Jayanti Park Indirapuram", "lat": 28.6432, "lon": 77.3685, "zone": "Ghaziabad"},
    {"name": "City Forest Ghaziabad", "lat": 28.6855, "lon": 77.4125, "zone": "Raj Nagar Extension"},
    {"name": "Town Park Faridabad", "lat": 28.3975, "lon": 77.3188, "zone": "Faridabad Sector 12"},
    {"name": "Badkhal Lake Eco Park", "lat": 28.4145, "lon": 77.2835, "zone": "Faridabad"},
    {"name": "Surajkund Green Complex", "lat": 28.4872, "lon": 77.2831, "zone": "Faridabad / Delhi Border"},
    {"name": "Coronation Park", "lat": 28.7214, "lon": 77.1975, "zone": "Burari Road"}
]

def get_db_connection():
    """Establish and return a PostgreSQL connection."""
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    dbname = os.getenv("DB_NAME", "hawaguide_db")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "")

    conn_params = {
        "host": host,
        "port": port,
        "dbname": dbname,
        "user": user,
    }
    if password:
        conn_params["password"] = password

    return psycopg2.connect(**conn_params)

def ensure_parks_table(conn):
    """Ensure the parks table exists in PostGIS with spatial geography points."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS parks (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                lat DOUBLE PRECISION NOT NULL,
                lon DOUBLE PRECISION NOT NULL,
                zone VARCHAR(255),
                location geography(Point, 4326)
            );
            CREATE INDEX IF NOT EXISTS idx_parks_location ON parks USING GIST (location);
        """)
        # Insert or update 40 parks
        for p in DELHI_NCR_PARKS:
            cur.execute("""
                INSERT INTO parks (name, lat, lon, zone, location)
                VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
                ON CONFLICT (name) DO UPDATE 
                SET lat = EXCLUDED.lat, lon = EXCLUDED.lon, zone = EXCLUDED.zone, location = EXCLUDED.location;
            """, (p["name"], p["lat"], p["lon"], p["zone"], p["lon"], p["lat"]))
    conn.commit()


# =================================================================================================
# 1. PERSONALIZED PEVI CALCULATION
# =================================================================================================

def get_age_multiplier(age_group: str) -> float:
    """
    Returns the vulnerability multiplier for the given age group.
    - Child (<18) or Elderly (65+): 1.3
    - Adult (general): 1.0
    """
    clean_age = str(age_group).strip().lower()
    if clean_age in ["child", "children", "kid", "kids", "elderly", "senior", "seniors", "old", "65+"]:
        return 1.3
    return 1.0

def get_condition_multiplier(condition: str) -> float:
    """
    Returns the vulnerability multiplier for underlying health conditions.
    - Respiratory (asthma, COPD, bronchitis) or Cardiac (heart disease): 1.5
    - Healthy / none: 1.0
    """
    clean_cond = str(condition).strip().lower()
    if clean_cond in ["respiratory", "cardiac", "asthma", "copd", "heart", "cardio", "lung"]:
        return 1.5
    return 1.0

def get_smoker_multiplier(smoker: bool) -> float:
    """
    Returns the susceptibility multiplier for tobacco smokers (1.25x vs 1.0x).
    """
    return 1.25 if smoker else 1.0

def get_activity_multiplier(planned_activity: str) -> float:
    """
    Returns the inhalation volume multiplier based on respiratory minute-ventilation (V_E).
    - Rest (1.0x) ~ 6-8 L/min
    - Moderate (1.3x) ~ 20-30 L/min
    - Vigorous (1.6x) ~ 45-65+ L/min
    """
    clean_act = str(planned_activity).strip().lower()
    if clean_act in ["vigorous", "intense", "running", "jogging", "cycling", "cardio", "high"]:
        return 1.6
    elif clean_act in ["moderate", "walking", "brisk", "yoga", "light_exercise"]:
        return 1.3
    else:
        return 1.0

def calculate_personalized_pevi(
    base_pevi: float,
    age_group: str = "adult",
    condition: str = "healthy",
    conditions: Optional[List[str]] = None,
    smoker: bool = False,
    planned_activity: str = "moderate",
    duration_hours: float = 1.0
) -> float:
    """
    Computes 5-factor Personalized PEVI:
        Personalized_PEVI = Base_PEVI × age_mult × cond_mult × smoker_mult × activity_mult × (1 + 0.15 × duration_hours)
    """
    age_mult = get_age_multiplier(age_group)
    
    # Check condition and conditions list
    cond_mult = get_condition_multiplier(condition)
    if conditions:
        for c in conditions:
            m = get_condition_multiplier(c)
            if m > cond_mult:
                cond_mult = m

    smoker_mult = get_smoker_multiplier(smoker)
    act_mult = get_activity_multiplier(planned_activity)
    dur_hours = max(0.0, float(duration_hours))
    dur_mult = 1.0 + (0.15 * dur_hours)
    
    total_mult = age_mult * cond_mult * smoker_mult * act_mult * dur_mult
    personalized = float(base_pevi) * total_mult
    return round(personalized, 4)


MEDICAL_DISCLAIMER = "This tool provides general environmental air quality guidance, not medical advice; consult a healthcare provider for personal health decisions."


def get_personalized_guidance(pers_pevi: float) -> str:
    """
    Returns consumer-friendly, non-prescriptive air quality advisory guidance (AirLief/AirVisual style).
    """
    val = float(pers_pevi)
    if val <= 6.00:
        return "Great conditions for outdoor activities and exercise."
    elif val <= 7.70:
        return "Acceptable for most outdoor activities; sensitive groups may want to consider shorter outdoor sessions."
    elif val <= 10.30:
        return "Higher air pollution exposure; sensitive groups may want to reduce strenuous outdoor activity or consider mask protection."
    else:
        return "Significantly elevated exposure; consider indoor activities or choosing a lower-risk nearby location."


def get_personalized_risk_band(pers_pevi: float) -> str:
    """
    Returns the relative vulnerability band for a **Personalized PEVI** score.
    Uses Personalized PEVI scale thresholds (empirical pooled distribution across
    representative demographic personas, N=160 across 4 sensitivity tiers):
        Band 1 Low:      pers_pevi <= 6.00
        Band 2 Moderate: 6.00 < pers_pevi <= 7.70
        Band 3 High:     7.70 < pers_pevi <= 10.30
        Band 4 Extreme:  pers_pevi > 10.30

    NOTE: Do NOT use this function for base PEVI values — use get_base_pevi_band() instead.
    """
    val = float(pers_pevi)
    if val <= 6.00:
        return "Low (Band 1)"
    elif val <= 7.70:
        return "Moderate (Band 2)"
    elif val <= 10.30:
        return "High (Band 3)"
    else:
        return "Extreme (Band 4)"


def get_base_pevi_band(base_pevi: float) -> str:
    """
    Returns the relative vulnerability band for a **Base PEVI** score.
    Uses the documented base PEVI quartile thresholds derived from the
    unweighted 40-park baseline distribution (ambient green space risk):
        Band 1 Low:      base_pevi <= 4.13  (Q1)
        Band 2 Moderate: 4.13 < base_pevi <= 4.81  (Q2)
        Band 3 High:     4.81 < base_pevi <= 5.65  (Q3)
        Band 4 Highest:  base_pevi > 5.65  (Q4)

    NOTE: Do NOT use get_personalized_risk_band() for base PEVI — its thresholds
    are calibrated to the personalized scale (6.0 / 7.7 / 10.3) and will severely
    underclassify base PEVI values (e.g. 6.23 → "Moderate" instead of "Highest").
    """
    val = float(base_pevi)
    if val <= 4.13:
        return "Low (Band 1)"
    elif val <= 4.81:
        return "Moderate (Band 2)"
    elif val <= 5.65:
        return "High (Band 3)"
    else:
        return "Highest (Band 4)"



# =================================================================================================
# 2. LOCATION OPTIMIZER (PostGIS ST_Distance + Min-Max Multi-Objective Ranking)
# =================================================================================================

def optimize_parks(
    start_lat: float,
    start_lon: float,
    age_group: str = "adult",
    condition: str = "healthy",
    conditions: Optional[List[str]] = None,
    smoker: bool = False,
    planned_activity: str = "moderate",
    duration_hours: float = 1.0,
    alpha: float = 0.5,
    conn = None
) -> List[Dict[str, Any]]:
    """
    Computes personalized PEVI (5-factor formula) and PostGIS geodetic distance for all 40 parks from (start_lat, start_lon).
    Normalizes both risk and distance to [0, 1], applies α trade-off weighting, and returns ranked parks.
    """
    alpha = max(0.0, min(1.0, float(alpha)))
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    ensure_parks_table(conn)

    # PostGIS spatial distance query joined with latest PEVI score per park
    query = """
        WITH latest_pevi AS (
            SELECT DISTINCT ON (location_name)
                location_name,
                pevi_value,
                timestamp
            FROM pevi_scores
            ORDER BY location_name, timestamp DESC
        )
        SELECT 
            p.id,
            p.name,
            p.lat,
            p.lon,
            p.zone,
            COALESCE(lp.pevi_value, 5.0) AS base_pevi,
            lp.timestamp AS pevi_timestamp,
            ST_Distance(
                p.location,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
            ) AS distance_meters
        FROM parks p
        LEFT JOIN latest_pevi lp ON p.name = lp.location_name
        ORDER BY p.name;
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, (start_lon, start_lat))
        rows = cur.fetchall()

    if close_conn:
        conn.close()

    if not rows:
        return []

    # Calculate Personalized PEVI and distances
    park_records = []
    for r in rows:
        dist_km = float(r["distance_meters"]) / 1000.0
        base_pevi = float(r["base_pevi"])
        pers_pevi = calculate_personalized_pevi(
            base_pevi=base_pevi,
            age_group=age_group,
            condition=condition,
            conditions=conditions,
            smoker=smoker,
            planned_activity=planned_activity,
            duration_hours=duration_hours
        )
        risk_band = get_personalized_risk_band(pers_pevi)
        guidance = get_personalized_guidance(pers_pevi)

        park_records.append({
            "id": r["id"],
            "name": r["name"],
            "zone": r["zone"],
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "distance_km": round(dist_km, 3),
            "distance_meters": round(float(r["distance_meters"]), 1),
            "base_pevi": round(base_pevi, 2),
            "personalized_pevi": pers_pevi,
            "personalized_risk_band": risk_band,
            "advisory_guidance": guidance,
            "_raw_dist_km": dist_km,
            "_raw_pers_pevi": pers_pevi,
        })

    # Min-max normalization across all 40 candidates
    risks = [p["_raw_pers_pevi"] for p in park_records]
    dists = [p["_raw_dist_km"] for p in park_records]

    min_risk, max_risk = min(risks), max(risks)
    min_dist, max_dist = min(dists), max(dists)

    risk_range = max_risk - min_risk if (max_risk - min_risk) > 1e-6 else 1.0
    dist_range = max_dist - min_dist if (max_dist - min_dist) > 1e-6 else 1.0

    for p in park_records:
        norm_r = (p["_raw_pers_pevi"] - min_risk) / risk_range
        norm_d = (p["_raw_dist_km"] - min_dist) / dist_range
        raw_score = (alpha * norm_r) + ((1.0 - alpha) * norm_d)

        p["norm_risk"] = round(norm_r, 6)
        p["norm_distance"] = round(norm_d, 6)
        p["score"] = round(raw_score, 6)
        p["_raw_score"] = raw_score

    # Sort ascending by exact raw composite score (lower is better)
    ranked_parks = sorted(park_records, key=lambda x: x["_raw_score"])

    for rank, p in enumerate(ranked_parks, start=1):
        p["rank"] = rank
        # Clean internal raw keys
        del p["_raw_dist_km"]
        del p["_raw_pers_pevi"]
        del p["_raw_score"]

    return ranked_parks


# =================================================================================================
# 3. CLI DEMONSTRATION & VERIFICATION
# =================================================================================================

if __name__ == "__main__":
    print("=" * 90)
    print("   HAWAGUIDE — PERSONALIZED PEVI & LOCATION OPTIMIZER VERIFICATION")
    print("=" * 90)

    # Example 1: Connaught Place start, Elderly with Respiratory condition, 2 hours, alpha=0.7
    cp_lat, cp_lon = 28.6328, 77.2197
    print(f"\n[Scenario 1] User at Connaught Place ({cp_lat}, {cp_lon})")
    print("  Profile : Age = Elderly (x1.3), Condition = Respiratory (x1.5), Duration = 2.0 hrs (x1.30)")
    print("  Weight  : Alpha = 0.7 (70% pollution risk minimization, 30% distance minimization)")
    
    ranked_1 = optimize_parks(
        start_lat=cp_lat,
        start_lon=cp_lon,
        age_group="elderly",
        condition="respiratory",
        duration_hours=2.0,
        alpha=0.7
    )

    print("\nTop 10 Recommended Parks:")
    print(f"{'Rank':<5} {'Park Name':<32} {'Zone':<24} {'Dist (km)':>10} {'Base PEVI':>10} {'Pers PEVI':>10} {'Score':>8}")
    print("-" * 105)
    for p in ranked_1[:10]:
        print(f"{p['rank']:<5} {p['name']:<32} {p['zone']:<24} {p['distance_km']:>10.2f} {p['base_pevi']:>10.2f} {p['personalized_pevi']:>10.2f} {p['score']:>8.4f}")

    # Example 2: South Delhi start, Adult Healthy, 1 hour, alpha=0.3 (convenience/distance priority)
    sd_lat, sd_lon = 28.5492, 77.2000
    print(f"\n" + "=" * 90)
    print(f"[Scenario 2] User in South Delhi / Hauz Khas ({sd_lat}, {sd_lon})")
    print("  Profile : Age = Adult (x1.0), Condition = Healthy (x1.0), Duration = 1.0 hr (x1.15)")
    print("  Weight  : Alpha = 0.3 (30% pollution risk, 70% distance minimization)")

    ranked_2 = optimize_parks(
        start_lat=sd_lat,
        start_lon=sd_lon,
        age_group="adult",
        condition="healthy",
        duration_hours=1.0,
        alpha=0.3
    )

    print("\nTop 10 Recommended Parks:")
    print(f"{'Rank':<5} {'Park Name':<32} {'Zone':<24} {'Dist (km)':>10} {'Base PEVI':>10} {'Pers PEVI':>10} {'Score':>8}")
    print("-" * 105)
    for p in ranked_2[:10]:
        print(f"{p['rank']:<5} {p['name']:<32} {p['zone']:<24} {p['distance_km']:>10.2f} {p['base_pevi']:>10.2f} {p['personalized_pevi']:>10.2f} {p['score']:>8.4f}")
    print("=" * 90)
