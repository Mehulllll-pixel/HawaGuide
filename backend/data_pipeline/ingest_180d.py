"""
===================================================================================================
HawaGuide - 180-Day Historical Data Ingestion (OpenAQ Readings + Open-Meteo Meteorology)
===================================================================================================

This script extends the historical database window from 90 days to 180 days (2026-03-08 to 2026-09-04)
for all 14 monitoring stations across Delhi NCR.
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
from psycopg2.extras import execute_values
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
    get_db_connection, ensure_db_schema, fetch_station_openaq_location,
    fetch_sensor_hourly_readings, insert_readings_batch,
    POLLUTANT_MAP, TARGET_POLLUTANTS
)
from weather_ingest import (
    init_weather_table, fetch_station_list, fetch_open_meteo_weather,
    parse_and_insert_weather
)

def run_180d_ingestion():
    api_key = os.getenv("OPENAQ_API_KEY")
    if not api_key:
        print("Error: OPENAQ_API_KEY not found in environment.", file=sys.stderr)
        sys.exit(1)

    ensure_db_schema()
    conn = get_db_connection()
    init_weather_table(conn)

    # 180-day window: 2026-03-08 to 2026-09-04 UTC
    end_dt = datetime(2026, 9, 5, 0, 0, 0, tzinfo=timezone.utc)
    start_dt = end_dt - timedelta(days=180)
    dt_from_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    dt_to_str = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    cutoff_str = start_dt.strftime("%Y-%m-%d")

    start_date_ymd = start_dt.strftime("%Y-%m-%d")
    end_date_ymd = end_dt.strftime("%Y-%m-%d")

    print("=" * 95)
    print("      HAWAGUIDE 180-DAY HISTORICAL INGESTION PIPELINE (OpenAQ + Open-Meteo)")
    print("=" * 95)
    print(f"Target Window:       {dt_from_str} to {dt_to_str} (180 Days)")
    print(f"Target Pollutants:   {', '.join(sorted(TARGET_POLLUTANTS))}")
    print("=" * 95 + "\n")

    # Step 1: Ingest OpenAQ Readings
    print("[1/2] Ingesting 180-day OpenAQ hourly pollutant readings...")
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, lat, lon FROM stations ORDER BY id;")
        stations = cur.fetchall()

    session = requests.Session()
    headers = {"X-API-Key": api_key, "Accept": "application/json"}

    total_stations = len(stations)
    total_readings = 0
    pollutant_counts = defaultdict(int)

    for idx, (st_id, name, lat, lon) in enumerate(stations, start=1):
        print(f"  [{idx:2d}/{total_stations}] Station ID {st_id:2d}: {name[:34]:<34}", end="", flush=True)
        loc = fetch_station_openaq_location(session, headers, lat, lon, name, cutoff_str)
        if not loc:
            print(" -> [!] No OpenAQ location found.")
            continue

        loc_id = loc.get("id")
        sensors = loc.get("sensors", [])
        matched_sensors = []
        for s in sensors:
            p_raw = s.get("parameter", {}).get("name", "").lower()
            norm = POLLUTANT_MAP.get(p_raw)
            if norm and norm in TARGET_POLLUTANTS:
                dt_last_s = s.get("datetimeLast", {}).get("utc") if isinstance(s.get("datetimeLast"), dict) else ""
                if not dt_last_s or dt_last_s >= cutoff_str:
                    matched_sensors.append((s.get("id"), norm))

        st_readings = []
        for s_id, pol in matched_sensors:
            s_reads = fetch_sensor_hourly_readings(session, headers, s_id, pol, dt_from_str, dt_to_str)
            for r in s_reads:
                pollutant_counts[r["pollutant"]] += 1
            st_readings.extend(s_reads)

        with conn.cursor() as cur:
            inserted = insert_readings_batch(cur, st_id, st_readings)
            conn.commit()

        total_readings += len(st_readings)
        print(f" -> Loc {loc_id:5d} | {len(matched_sensors):2d} sensors | {len(st_readings):,d} readings", flush=True)
        time.sleep(0.3)

    print(f"\n[+] Total OpenAQ readings processed: {total_readings:,}")

    # Step 2: Ingest Open-Meteo Weather
    print("\n[2/2] Ingesting 180-day Open-Meteo hourly meteorology...")
    print(f"      Window: {start_date_ymd} to {end_date_ymd}")
    total_weather_inserted = 0

    st_list = fetch_station_list(conn)
    for idx, st in enumerate(st_list, start=1):
        st_id = st["id"]
        name = st["name"]
        lat = st["lat"]
        lon = st["lon"]
        print(f"  [{idx:2d}/{len(st_list)}] Weather for Station {st_id:2d}: {name[:34]:<34}", end="", flush=True)
        try:
            w_data = fetch_open_meteo_weather(lat, lon, start_date_ymd, end_date_ymd)
            inserted_w = parse_and_insert_weather(conn, st_id, w_data)
            total_weather_inserted += inserted_w
            print(f" -> +{inserted_w:,} hourly rows", flush=True)
        except Exception as e:
            print(f" -> ERROR: {e}", flush=True)
        time.sleep(0.4)

    print(f"\n[+] Total weather records inserted/updated: {total_weather_inserted:,}")

    # Final DB Verification
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM readings WHERE pollutant = 'pm25';")
        pm_min, pm_max, pm_cnt = cur.fetchone()
        cur.execute("SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM weather;")
        w_min, w_max, w_cnt = cur.fetchone()

    print("\n" + "=" * 95)
    print("                      DATABASE STATE POST-INGESTION")
    print("=" * 95)
    print(f"PM2.5 Readings:  {pm_cnt:,} rows  |  Range: {pm_min} -> {pm_max}")
    print(f"Weather Records: {w_cnt:,} rows  |  Range: {w_min} -> {w_max}")
    print("=" * 95 + "\n")

    conn.close()

if __name__ == "__main__":
    run_180d_ingestion()
