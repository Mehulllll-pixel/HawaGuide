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

# Search and load .env from backend/ directory, project root, or cwd
BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

for candidate in [BACKEND_DIR / ".env", PROJECT_ROOT / ".env", Path(".env")]:
    if candidate.is_file():
        load_dotenv(dotenv_path=candidate)
        break
else:
    load_dotenv()

TARGET_POLLUTANTS = {"pm25", "pm10", "no2", "so2", "o3", "co"}

# Pollutant name normalization map
POLLUTANT_MAP = {
    "pm25": "pm25",
    "pm2.5": "pm25",
    "pm10": "pm10",
    "no2": "no2",
    "so2": "so2",
    "o3": "o3",
    "co": "co"
}


def get_db_connection():
    """Establish and return a connection to PostgreSQL database."""
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url)
    
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    dbname = os.getenv("DB_NAME", "hawaguide_db")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD")
    
    conn_params = {
        "host": host,
        "port": port,
        "dbname": dbname,
        "user": user,
    }
    if password is not None:
        conn_params["password"] = password
        
    return psycopg2.connect(**conn_params)


def ensure_db_schema():
    """Ensure unique constraint on readings(station_id, pollutant, timestamp) exists."""
    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()
    try:
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_readings_station_pollutant_ts'
                ) THEN
                    ALTER TABLE readings ADD CONSTRAINT uq_readings_station_pollutant_ts 
                    UNIQUE (station_id, pollutant, timestamp);
                END IF;
            END $$;
        """)
    finally:
        cursor.close()
        conn.close()


def make_openaq_request(session, url, headers, params=None, max_retries=3):
    """
    Execute HTTP GET request to OpenAQ API with rate-limit handling and retries.
    """
    for attempt in range(1, max_retries + 1):
        try:
            # Respect rate limit with polite pause
            time.sleep(0.2)
            response = session.get(url, headers=headers, params=params, timeout=20)
            
            if response.status_code == 429:
                wait_time = attempt * 2
                print(f"  [Rate limit 429] Backing off for {wait_time}s (attempt {attempt}/{max_retries})...")
                time.sleep(wait_time)
                continue
            
            if response.status_code == 401:
                raise ValueError("Invalid or unauthorized OpenAQ API Key. Please verify OPENAQ_API_KEY in your .env file.")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt == max_retries:
                print(f"  [Warning] Request failed after {max_retries} attempts: {e}")
                return None
            time.sleep(attempt * 1.5)
    return None


def fetch_station_openaq_location(session, headers, lat, lon, name, cutoff_str):
    """
    Find matching active OpenAQ location for a station using coordinates, name matching, and active date filter.
    """
    url = "https://api.openaq.org/v3/locations"
    params = {
        "coordinates": f"{lat},{lon}",
        "radius": 3500,
        "limit": 15
    }
    data = make_openaq_request(session, url, headers, params)
    if not data or not data.get("results"):
        return None

    results = data["results"]
    
    # Priority 1: Locations active within cutoff, ranked by keyword/token overlap
    active_candidates = []
    for loc in results:
        dt_last = loc.get("datetimeLast") or {}
        last_utc = dt_last.get("utc") if isinstance(dt_last, dict) else ""
        if last_utc and last_utc >= cutoff_str and loc.get("sensors"):
            # Compute token overlap
            target_tokens = set(name.lower().replace(",", " ").replace("-", " ").split())
            loc_tokens = set(loc.get("name", "").lower().replace(",", " ").replace("-", " ").split())
            overlap = len(target_tokens & loc_tokens)
            active_candidates.append((overlap, loc))
    
    if active_candidates:
        active_candidates.sort(key=lambda x: x[0], reverse=True)
        return active_candidates[0][1]

    # Priority 2: Closest active location with sensors
    for loc in results:
        dt_last = loc.get("datetimeLast") or {}
        last_utc = dt_last.get("utc") if isinstance(dt_last, dict) else ""
        if last_utc and last_utc >= cutoff_str:
            return loc

    return results[0]


def fetch_sensor_hourly_readings(session, headers, sensor_id, pollutant, dt_from_str, dt_to_str):
    """
    Fetch all hourly measurements for a specific sensor in the datetime range.
    Handles pagination automatically.
    """
    url = f"https://api.openaq.org/v3/sensors/{sensor_id}/hours"
    readings = []
    page = 1
    page_limit = 1000

    while True:
        params = {
            "datetime_from": dt_from_str,
            "datetime_to": dt_to_str,
            "limit": page_limit,
            "page": page
        }
        data = make_openaq_request(session, url, headers, params)
        if not data:
            break

        results = data.get("results", [])
        if not results:
            break

        for item in results:
            val = item.get("value")
            if val is None:
                continue
            
            try:
                val_float = float(val)
            except (ValueError, TypeError):
                continue
            
            # Skip invalid negative readings
            if val_float < 0:
                continue

            period = item.get("period") or {}
            dt_to_obj = period.get("datetimeTo") or {}
            dt_from_obj = period.get("datetimeFrom") or {}
            
            ts_str = dt_to_obj.get("utc") or dt_from_obj.get("utc") or item.get("datetime", {}).get("utc")
            if not ts_str:
                continue

            readings.append({
                "pollutant": pollutant,
                "value": val_float,
                "timestamp": ts_str
            })

        meta = data.get("meta", {})
        found = meta.get("found", 0)
        # If fewer results returned than limit or reached total found, stop pagination
        if len(results) < page_limit:
            break
        page += 1

    return readings


def insert_readings_batch(cursor, station_id, readings):
    """
    Insert a batch of reading records into PostgreSQL readings table.
    """
    if not readings:
        return 0

    query = """
        INSERT INTO readings (station_id, pollutant, value, timestamp)
        VALUES %s
        ON CONFLICT (station_id, pollutant, timestamp) DO NOTHING;
    """
    records = [
        (station_id, r["pollutant"], r["value"], r["timestamp"])
        for r in readings
    ]
    
    execute_values(cursor, query, records, template=None, page_size=1000)
    return len(records)


def main():
    api_key = os.getenv("OPENAQ_API_KEY")
    if not api_key:
        print("Error: OPENAQ_API_KEY is not set in environment or backend/.env file.", file=sys.stderr)
        print("Please add 'OPENAQ_API_KEY=your_key_here' to your backend/.env file.", file=sys.stderr)
        sys.exit(1)

    ensure_db_schema()

    # Time range: Last 90 days
    now_utc = datetime.now(timezone.utc)
    from_utc = now_utc - timedelta(days=90)
    dt_from_str = from_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    dt_to_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"Fetching OpenAQ v3 hourly readings for the last 90 days:")
    print(f"  - From: {dt_from_str}")
    print(f"  - To:   {dt_to_str}")
    print(f"  - Pollutants: {', '.join(sorted(TARGET_POLLUTANTS))}\n")

    conn = get_db_connection()
    conn.autocommit = False
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT id, name, lat, lon FROM stations ORDER BY id;")
        stations = cursor.fetchall()
    except Exception as e:
        print(f"Error fetching stations from database: {e}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    total_stations = len(stations)
    print(f"Found {total_stations} station(s) in database.\n")

    session = requests.Session()
    headers = {
        "X-API-Key": api_key,
        "Accept": "application/json"
    }

    pollutant_counts = defaultdict(int)
    station_counts = defaultdict(int)
    total_readings_inserted = 0

    cutoff_str = from_utc.strftime("%Y-%m-%d")

    for idx, (station_id, name, lat, lon) in enumerate(stations, start=1):
        print(f"[{idx}/{total_stations}] Station ID {station_id}: {name}")
        
        # Locate corresponding OpenAQ location
        loc = fetch_station_openaq_location(session, headers, lat, lon, name, cutoff_str)
        if not loc:
            print("  -> Could not locate OpenAQ location within radius. Skipping.\n")
            continue

        openaq_loc_id = loc.get("id")
        sensors = loc.get("sensors", [])
        
        # Filter sensors for target pollutants
        matched_sensors = []
        for s in sensors:
            p_raw = s.get("parameter", {}).get("name", "").lower()
            normalized = POLLUTANT_MAP.get(p_raw)
            if normalized and normalized in TARGET_POLLUTANTS:
                matched_sensors.append((s.get("id"), normalized))

        if not matched_sensors:
            print(f"  -> OpenAQ Location ID {openaq_loc_id}: No matching target sensors found.\n")
            continue

        unique_pols = sorted(list(set(p for _, p in matched_sensors)))
        print(f"  -> OpenAQ Location ID {openaq_loc_id} | {len(matched_sensors)} sensor(s) ({', '.join(unique_pols)})")

        station_readings = []
        for sensor_id, pollutant in matched_sensors:
            sensor_readings = fetch_sensor_hourly_readings(
                session, headers, sensor_id, pollutant, dt_from_str, dt_to_str
            )
            for r in sensor_readings:
                pollutant_counts[r["pollutant"]] += 1
            station_readings.extend(sensor_readings)

        # Batch insert into database
        if station_readings:
            inserted = insert_readings_batch(cursor, station_id, station_readings)
            conn.commit()
            station_counts[name] += len(station_readings)
            total_readings_inserted += len(station_readings)
            print(f"  -> Stored {len(station_readings):,} readings in database.\n")
        else:
            print("  -> 0 measurements available in the last 90 days for this station.\n")

    # Fetch total distinct rows currently in readings table
    cursor.execute("SELECT count(*) FROM readings;")
    db_total_count = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    # Print Final Summary
    print("=" * 65)
    print("                    DATA INGESTION SUMMARY")
    print("=" * 65)
    print(f"Stations Processed:        {total_stations}")
    print(f"Total Readings Processed:  {total_readings_inserted:,}")
    print(f"Total Database Rows:       {db_total_count:,}")
    print("-" * 65)
    print("Readings Count by Pollutant:")
    print(f"  {'Pollutant':<15} {'Readings Count':>15}")
    print(f"  {'-'*15} {'-'*15}")
    for pol in sorted(TARGET_POLLUTANTS):
        cnt = pollutant_counts.get(pol, 0)
        print(f"  {pol:<15} {cnt:>15,}")
    print("-" * 65)
    print("Readings Count by Station:")
    print(f"  {'Station Name':<45} {'Readings':>15}")
    print(f"  {'-'*45} {'-'*15}")
    for _, name, _, _ in stations:
        cnt = station_counts.get(name, 0)
        print(f"  {name:<45} {cnt:>15,}")
    print("=" * 65)


if __name__ == "__main__":
    main()
