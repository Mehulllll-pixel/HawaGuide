"""
===================================================================================================
HawaGuide — CI Test Database Seeder
===================================================================================================
Initializes database schema and populates realistic synthetic monitoring stations,
24-hour multi-pollutant readings, park locations, and PEVI baseline records for CI workflows.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

for candidate in [PROJECT_ROOT / "backend" / ".env", PROJECT_ROOT / ".env", Path(".env")]:
    if candidate.is_file():
        load_dotenv(dotenv_path=candidate)
        break
else:
    load_dotenv()

from backend.data_pipeline.setup_db import setup_database, get_db_connection
from backend.ml.optimizer import DELHI_NCR_PARKS

# 14 Standard Regulatory Monitoring Stations across NCR
MONITORING_STATIONS = [
    {"name": "Anand Vihar, Delhi - DPCC", "lat": 28.6482, "lon": 77.3160},
    {"name": "Punjabi Bagh, Delhi - DPCC", "lat": 28.6740, "lon": 77.1310},
    {"name": "Mandir Marg, Delhi - DPCC", "lat": 28.6360, "lon": 77.2010},
    {"name": "R K Puram, Delhi - DPCC", "lat": 28.5630, "lon": 77.1860},
    {"name": "Jawaharlal Nehru Stadium, Delhi - DPCC", "lat": 28.5800, "lon": 77.2340},
    {"name": "Siri Fort, Delhi - CPCB", "lat": 28.5500, "lon": 77.2150},
    {"name": "NSIT Dwarka, Delhi - CPCB", "lat": 28.6090, "lon": 77.0320},
    {"name": "IHBAS, Dilshad Garden, Delhi - CPCB", "lat": 28.6810, "lon": 77.3150},
    {"name": "Major Dhyan Chand National Stadium, Delhi - DPCC", "lat": 28.6130, "lon": 77.2380},
    {"name": "Sector-62, Noida - IMD", "lat": 28.6240, "lon": 77.3650},
    {"name": "Sector-125, Noida - UPPCB", "lat": 28.5440, "lon": 77.3330},
    {"name": "Vikas Sadan, Gurgaon - HSPCB", "lat": 28.4500, "lon": 77.0260},
    {"name": "Sector-51, Gurugram - HSPCB", "lat": 28.4230, "lon": 77.0710},
    {"name": "Sector 16A, Faridabad - HSPCB", "lat": 28.4080, "lon": 77.3180},
]

BASELINES = {
    "pm25": 45.0,
    "pm10": 130.0,
    "no2": 28.0,
    "so2": 15.0,
    "o3": 25.0,
    "co": 0.85,
}


def seed_ci_database():
    print("Initializing database schema...")
    setup_database()

    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()

    print("Seeding 14 reference monitoring stations...")
    for s in MONITORING_STATIONS:
        cursor.execute("""
            INSERT INTO stations (name, lat, lon, location)
            VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
            ON CONFLICT (name) DO UPDATE SET lat = EXCLUDED.lat, lon = EXCLUDED.lon;
        """, (s["name"], s["lat"], s["lon"], s["lon"], s["lat"]))

    cursor.execute("SELECT id, name, lat, lon FROM stations;")
    stations = cursor.fetchall()
    print(f"Registered {len(stations)} monitoring stations.")

    print("Generating 24-hour synthetic multi-pollutant readings for each station...")
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    readings = []

    np.random.seed(42)
    for s_id, s_name, lat, lon in stations:
        # Spatial gradient based on coordinates (higher in NW / E)
        spatial_factor = 1.0 + 0.2 * (lat - 28.5) - 0.15 * (lon - 77.2)
        for h in range(24):
            ts = now - timedelta(hours=h)
            for pol, base in BASELINES.items():
                noise = np.random.normal(0, base * 0.08)
                val = max(1.0, float(base * spatial_factor + noise))
                readings.append((s_id, pol, val, ts))

    execute_values(
        cursor,
        """
        INSERT INTO readings (station_id, pollutant, value, timestamp)
        VALUES %s
        ON CONFLICT (station_id, pollutant, timestamp) DO NOTHING;
        """,
        readings
    )
    print(f"Seeded {len(readings)} readings.")

    print("Seeding baseline records for 40 Delhi NCR green spaces...")
    for p in DELHI_NCR_PARKS:
        cursor.execute("""
            INSERT INTO pevi_scores (location_name, pevi_value, timestamp, pm25_ugm3, pm10_ugm3, no2_ugm3, so2_ugm3, o3_ugm3, co_mgm3)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING;
        """, (p["name"], 4.50, now, 42.0, 125.0, 26.0, 14.0, 24.0, 0.80))

        for pol, base in BASELINES.items():
            cursor.execute("""
                INSERT INTO interpolated_locations (location_name, lat, lon, pollutant, value, timestamp, location)
                VALUES (%s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
                ON CONFLICT (location_name, pollutant, timestamp) DO NOTHING;
            """, (p["name"], p["lat"], p["lon"], pol, base, now, p["lon"], p["lat"]))

    conn.close()
    print("CI database seed completed successfully!")


if __name__ == "__main__":
    seed_ci_database()
