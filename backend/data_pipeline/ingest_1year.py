"""
===================================================================================================
HawaGuide - 1-Year (365-Day) Historical Data Ingestion (OpenAQ Readings + Open-Meteo Meteorology)
===================================================================================================

This script ingests a full 1-year continuous dataset (2025-09-05 to 2026-09-04) across all 14 stations,
capturing the full annual cycle (Winter Smog, Spring, Summer Heat, and Monsoon).
===================================================================================================
"""

import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict
import requests
import psycopg2
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

for candidate in [BACKEND_DIR / ".env", PROJECT_ROOT / ".env", Path(".env")]:
    if candidate.is_file():
        load_dotenv(dotenv_path=candidate)
        break
else:
    load_dotenv()

from openaq_readings import (
    get_db_connection, ensure_db_schema,
    fetch_sensor_hourly_readings, insert_readings_batch,
    POLLUTANT_MAP, TARGET_POLLUTANTS
)
from weather_ingest import (
    init_weather_table, fetch_station_list, fetch_open_meteo_weather,
    parse_and_insert_weather
)

# Active OpenAQ locations and sensors for the 14 stations (continuous from 2025-02-18 onwards)
STATION_OPENAQ_MAP = [
    ( 4, "R K Puram, Delhi - DPCC", 17),
    ( 5, "Punjabi Bagh, Delhi - DPCC", 50),
    (13, "Pusa, Delhi - IMD", 5404),
    (14, "Anand Vihar, Delhi - DPCC", 235),
    (15, "Burari Crossing, New Delhi - IMD", 5541),
    (81, "Aya Nagar, New Delhi - IMD", 5570),
    (82, "Sirifort, Delhi - CPCB", 5586),
    (83, "Sector - 125, Noida, UP - UPPCB", 5598),
    (84, "North Campus, DU, Delhi - IMD", 5610),
    (85, "ITO, New Delhi - CPCB", 5613),
    (86, "Sector - 62, Noida, UP - IMD", 5616),
    (87, "NSIT Dwarka, Delhi - CPCB", 5622),
    (88, "DTU, New Delhi - CPCB", 5626),
    (89, "CRRI Mathura Road, New Delhi - IMD", 5627),
]

def run_1year_ingestion():
    api_key = os.getenv("OPENAQ_API_KEY")
    if not api_key:
        print("Error: OPENAQ_API_KEY not found in environment.", file=sys.stderr)
        sys.exit(1)

    ensure_db_schema()
    conn = get_db_connection()
    init_weather_table(conn)

    # 365-day window: 2025-09-05 to 2026-09-04 UTC
    end_dt = datetime(2026, 9, 5, 0, 0, 0, tzinfo=timezone.utc)
    start_dt = end_dt - timedelta(days=365)
    dt_from_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    dt_to_str = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    start_date_ymd = start_dt.strftime("%Y-%m-%d")
    end_date_ymd = end_dt.strftime("%Y-%m-%d")

    print("=" * 95)
    print("      HAWAGUIDE 1-YEAR (365-DAY) HISTORICAL INGESTION PIPELINE")
    print("=" * 95)
    print(f"Target Window:       {dt_from_str} to {dt_to_str} (365 Days / 1 Full Year)")
    print(f"Target Pollutants:   {', '.join(sorted(TARGET_POLLUTANTS))}")
    print("=" * 95 + "\n")

    session = requests.Session()
    headers = {"X-API-Key": api_key, "Accept": "application/json"}

    # Step 1: Ingest 1-Year OpenAQ Readings
    print("[1/2] Ingesting 365-day OpenAQ hourly pollutant readings...")
    total_readings = 0

    for idx, (st_id, name, loc_id) in enumerate(STATION_OPENAQ_MAP, start=1):
        print(f"  [{idx:2d}/14] Station ID {st_id:2d}: {name[:32]:<32} (Loc {loc_id:5d})", end="", flush=True)
        # Fetch location detail to get active sensors
        r_loc = session.get(f"https://api.openaq.org/v3/locations/{loc_id}", headers=headers, timeout=15)
        sensors = r_loc.json().get("results", [{}])[0].get("sensors", []) if r_loc.status_code == 200 else []
        
        matched_sensors = []
        for s in sensors:
            p_raw = s.get("parameter", {}).get("name", "").lower()
            norm = POLLUTANT_MAP.get(p_raw)
            if norm and norm in TARGET_POLLUTANTS:
                dt_last_s = s.get("datetimeLast", {}).get("utc") if isinstance(s.get("datetimeLast"), dict) else ""
                # Keep active 2026 sensors
                if not dt_last_s or dt_last_s >= "2026-06-01":
                    matched_sensors.append((s.get("id"), norm))

        st_readings = []
        for s_id, pol in matched_sensors:
            s_reads = fetch_sensor_hourly_readings(session, headers, s_id, pol, dt_from_str, dt_to_str)
            st_readings.extend(s_reads)

        with conn.cursor() as cur:
            inserted = insert_readings_batch(cur, st_id, st_readings)
            conn.commit()

        total_readings += len(st_readings)
        print(f" -> {len(matched_sensors):2d} sensors | {len(st_readings):,d} readings", flush=True)
        time.sleep(0.3)

    print(f"\n[+] Total OpenAQ readings processed: {total_readings:,}")

    # Step 2: Ingest 1-Year Open-Meteo Weather
    print("\n[2/2] Ingesting 365-day Open-Meteo hourly meteorology...")
    print(f"      Window: {start_date_ymd} to {end_date_ymd}")
    total_weather = 0

    st_list = fetch_station_list(conn)
    for idx, st in enumerate(st_list, start=1):
        st_id = st["id"]
        name = st["name"]
        lat = st["lat"]
        lon = st["lon"]
        print(f"  [{idx:2d}/{len(st_list)}] Weather for Station {st_id:2d}: {name[:32]:<32}", end="", flush=True)
        try:
            w_data = fetch_open_meteo_weather(lat, lon, start_date_ymd, end_date_ymd)
            inserted_w = parse_and_insert_weather(conn, st_id, w_data)
            total_weather += inserted_w
            print(f" -> +{inserted_w:,} hourly rows", flush=True)
        except Exception as e:
            print(f" -> ERROR: {e}", flush=True)
        time.sleep(0.4)

    print(f"\n[+] Total weather records inserted/updated: {total_weather:,}")

    # Step 3: Final DB Verification
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM readings WHERE pollutant = 'pm25';")
        pm_min, pm_max, pm_cnt = cur.fetchone()
        cur.execute("SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM weather;")
        w_min, w_max, w_cnt = cur.fetchone()

    print("\n" + "=" * 95)
    print("                      DATABASE STATE POST-INGESTION (1-YEAR)")
    print("=" * 95)
    print(f"PM2.5 Readings:  {pm_cnt:,} rows  |  Range: {pm_min} -> {pm_max}")
    print(f"Weather Records: {w_cnt:,} rows  |  Range: {w_min} -> {w_max}")
    print("=" * 95 + "\n")

    conn.close()

if __name__ == "__main__":
    run_1year_ingestion()
