"""
===================================================================================================
HawaGuide - Meteorological Data Ingestion Pipeline (Open-Meteo Historical Archive)
===================================================================================================

Module Overview:
----------------
This script ingests historical hourly weather observations for all 14 Delhi NCR monitoring stations
from the Open-Meteo Historical Weather API (https://archive-api.open-meteo.com/v1/archive).

Variables Ingested:
-------------------
1. wind_speed_10m        (km/h -> wind speed at 10 meters above ground)
2. wind_direction_10m    (degrees -> wind direction at 10 meters)
3. relative_humidity_2m  (% -> relative humidity at 2 meters)
4. precipitation         (mm -> rain/precipitation)
5. temperature_2m        (°C -> air temperature at 2 meters)

Temporal Window:
----------------
- Matches the 90-day pollution dataset: 2026-06-06 to 2026-09-04 (UTC)

Storage:
--------
- Stored into PostgreSQL 'weather' table with composite unique constraint (station_id, timestamp).
===================================================================================================
"""

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Tuple
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

OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
START_DATE = "2026-06-06"
END_DATE = "2026-09-04"

HOURLY_VARIABLES = [
    "wind_speed_10m",
    "wind_direction_10m",
    "relative_humidity_2m",
    "precipitation",
    "temperature_2m",
]


def get_db_connection():
    """Establish and return a connection to the PostgreSQL database."""
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


def init_weather_table(conn):
    """Ensure the weather table and indexes exist in PostgreSQL."""
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS weather (
        id BIGSERIAL PRIMARY KEY,
        station_id BIGINT NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
        timestamp TIMESTAMPTZ NOT NULL,
        wind_speed DOUBLE PRECISION,
        wind_direction DOUBLE PRECISION,
        humidity DOUBLE PRECISION,
        precipitation DOUBLE PRECISION,
        temperature DOUBLE PRECISION,
        CONSTRAINT uq_weather_station_ts UNIQUE (station_id, timestamp)
    );

    CREATE INDEX IF NOT EXISTS idx_weather_station_id ON weather (station_id);
    CREATE INDEX IF NOT EXISTS idx_weather_timestamp ON weather (timestamp);
    """
    with conn.cursor() as cur:
        cur.execute(create_table_sql)
    conn.commit()


def fetch_station_list(conn) -> List[Dict[str, Any]]:
    """Retrieve all active air quality stations and their coordinates."""
    query = "SELECT id, name, lat, lon FROM stations ORDER BY id;"
    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()
        
    stations = []
    for r in rows:
        stations.append({
            "id": r[0],
            "name": r[1],
            "lat": float(r[2]),
            "lon": float(r[3]),
        })
    return stations


def fetch_open_meteo_weather(lat: float, lon: float, start_date: str, end_date: str, max_retries: int = 3) -> Dict[str, Any]:
    """
    Query Open-Meteo Historical Archive API for hourly meteorological metrics.
    """
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "start_date": start_date,
        "end_date": end_date,
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "UTC"
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(OPEN_METEO_ARCHIVE_URL, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait_time = attempt * 2.0
                print(f"    [!] Rate limit hit (429), backing off for {wait_time:.1f}s...")
                time.sleep(wait_time)
            else:
                print(f"    [!] HTTP {resp.status_code} on attempt {attempt}: {resp.text[:100]}")
                time.sleep(1.0)
        except requests.RequestException as e:
            print(f"    [!] Request error on attempt {attempt}: {e}")
            time.sleep(1.0)

    raise RuntimeError(f"Failed to fetch weather data for ({lat}, {lon}) after {max_retries} attempts.")


def parse_and_insert_weather(conn, station_id: int, api_data: Dict[str, Any]) -> int:
    """
    Parse the API response and upsert records into the 'weather' table.
    """
    hourly = api_data.get("hourly", {})
    times = hourly.get("time", [])
    wind_speeds = hourly.get("wind_speed_10m", [])
    wind_directions = hourly.get("wind_direction_10m", [])
    humidities = hourly.get("relative_humidity_2m", [])
    precipitations = hourly.get("precipitation", [])
    temperatures = hourly.get("temperature_2m", [])

    records = []
    for i, t_str in enumerate(times):
        # Open-Meteo with timezone=UTC returns format 'YYYY-MM-DDTHH:MM'
        # Parse into UTC datetime
        dt = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
        ws = wind_speeds[i] if i < len(wind_speeds) else None
        wd = wind_directions[i] if i < len(wind_directions) else None
        hum = humidities[i] if i < len(humidities) else None
        prec = precipitations[i] if i < len(precipitations) else None
        temp = temperatures[i] if i < len(temperatures) else None

        records.append((station_id, dt, ws, wd, hum, prec, temp))

    if not records:
        return 0

    insert_sql = """
    INSERT INTO weather (station_id, timestamp, wind_speed, wind_direction, humidity, precipitation, temperature)
    VALUES %s
    ON CONFLICT (station_id, timestamp)
    DO UPDATE SET
        wind_speed = EXCLUDED.wind_speed,
        wind_direction = EXCLUDED.wind_direction,
        humidity = EXCLUDED.humidity,
        precipitation = EXCLUDED.precipitation,
        temperature = EXCLUDED.temperature;
    """

    with conn.cursor() as cur:
        execute_values(cur, insert_sql, records, page_size=1000)
    conn.commit()

    return len(records)


def run_weather_ingestion():
    """Main execution function for weather ingestion pipeline."""
    print("=" * 90)
    print("        HAWAGUIDE METEOROLOGICAL INGESTION (Open-Meteo Historical Archive API)")
    print("=" * 90)
    print(f"Target Window:  {START_DATE} to {END_DATE} (UTC)")
    print(f"Variables:      {', '.join(HOURLY_VARIABLES)}")
    print(f"API Endpoint:   {OPEN_METEO_ARCHIVE_URL}\n")

    conn = get_db_connection()
    try:
        print("[1/3] Initializing 'weather' table in PostgreSQL...", flush=True)
        init_weather_table(conn)
        print("      [+] Table 'weather' and indexes ready.")

        print("\n[2/3] Fetching station list from database...", flush=True)
        stations = fetch_station_list(conn)
        print(f"      [+] Found {len(stations)} monitoring stations.\n")

        print("[3/3] Ingesting hourly weather data per station...")
        print("-" * 90)
        print(f"{'#':<3} {'Station ID':<12} {'Station Name':<34} {'Coordinates':<20} {'Records':>10} {'Status':<10}")
        print("-" * 90)

        total_records = 0
        start_time = time.time()

        for idx, st in enumerate(stations, start=1):
            st_id = st["id"]
            st_name = st["name"]
            lat = st["lat"]
            lon = st["lon"]
            coords_str = f"({lat:.3f}, {lon:.3f})"

            try:
                data = fetch_open_meteo_weather(lat, lon, START_DATE, END_DATE)
                inserted_count = parse_and_insert_weather(conn, st_id, data)
                total_records += inserted_count
                status = f"OK (+{inserted_count})"
            except Exception as e:
                status = f"ERROR: {str(e)[:15]}"
                inserted_count = 0

            print(f"{idx:<3} {st_id:<12} {st_name[:32]:<34} {coords_str:<20} {inserted_count:>10} {status:<10}", flush=True)
            # Polite delay to respect free API rate limits
            time.sleep(0.4)

        elapsed = time.time() - start_time
        print("-" * 90)
        print(f"\n[+] Ingestion Complete in {elapsed:.2f}s!")
        print(f"[+] Total weather records ingested/updated: {total_records:,} across {len(stations)} stations.")

        # Print quick summary stats from database
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    COUNT(*) AS total_rows,
                    MIN(timestamp) AS min_ts,
                    MAX(timestamp) AS max_ts,
                    AVG(wind_speed) AS avg_wind,
                    AVG(humidity) AS avg_hum,
                    AVG(temperature) AS avg_temp,
                    SUM(precipitation) AS total_rain
                FROM weather;
            """)
            row = cur.fetchone()
            print("\nDatabase Weather Summary Statistics:")
            print(f"  - Total Rows:         {row[0]:,}")
            print(f"  - Earliest Timestamp: {row[1]}")
            print(f"  - Latest Timestamp:   {row[2]}")
            print(f"  - Mean Wind Speed:    {row[3]:.2f} km/h")
            print(f"  - Mean Humidity:      {row[4]:.1f} %")
            print(f"  - Mean Temperature:   {row[5]:.1f} °C")
            print(f"  - Cumulative Rain:    {row[6]:.1f} mm across all station-hours")
        print("=" * 90 + "\n")

    finally:
        conn.close()


if __name__ == "__main__":
    run_weather_ingestion()
