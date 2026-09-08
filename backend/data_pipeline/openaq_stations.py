import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import psycopg2
import requests
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
    """Ensure unique constraint on stations(name) exists."""
    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()
    try:
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'uq_stations_name'
                ) THEN
                    ALTER TABLE stations ADD CONSTRAINT uq_stations_name UNIQUE (name);
                END IF;
            END $$;
        """)
    finally:
        cursor.close()
        conn.close()


def fetch_delhi_stations(api_key: str, target_count: int = 14):
    """
    Fetch active air quality monitoring locations in Delhi NCR using OpenAQ v3 API.
    Filters for stations currently reporting (datetimeLast within the last 90 days).
    """
    url = "https://api.openaq.org/v3/locations"
    headers = {
        "X-API-Key": api_key,
        "Accept": "application/json"
    }

    # Time threshold for active stations (last 90 days)
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=90)
    cutoff_str = cutoff_dt.strftime("%Y-%m-%d")

    # Search centers across Delhi NCR
    search_centers = [
        ("Central Delhi", "28.6139,77.2090"),
        ("North Delhi", "28.7041,77.1025"),
        ("South Delhi / Okhla", "28.5355,77.2712"),
        ("North-West / Rohini", "28.7382,77.0822"),
        ("East Delhi / Anand Vihar", "28.6476,77.3158"),
        ("West Delhi / Punjabi Bagh", "28.6740,77.1310")
    ]

    seen_names = set()
    existing_coords = []
    stations = []

    # Pre-populate with existing DB stations if present
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name, lat, lon FROM stations;")
        for row in cursor.fetchall():
            s_name = row[0].strip()
            seen_names.add(s_name)
            s_lat = float(row[1])
            s_lon = float(row[2])
            existing_coords.append((s_lat, s_lon))
            stations.append({
                "name": s_name,
                "lat": s_lat,
                "lon": s_lon
            })
        cursor.close()
        conn.close()
    except Exception:
        pass

    target_pollutants = {"pm25", "pm10", "no2", "so2", "o3", "co"}

    for label, coords in search_centers:
        if len(stations) >= target_count:
            break

        print(f"Querying OpenAQ v3 for active locations near {label} (coordinates: {coords}, radius: 25000m)...")
        params = {
            "coordinates": coords,
            "radius": 25000,
            "limit": 50
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
            if response.status_code == 401:
                raise ValueError("Invalid or unauthorized OpenAQ API Key. Please verify OPENAQ_API_KEY in your .env file.")
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
        except Exception as e:
            print(f"  Warning: Request to {label} failed: {e}")
            continue

        for item in results:
            name = item.get("name")
            coord_data = item.get("coordinates") or {}
            lat = coord_data.get("latitude")
            lon = coord_data.get("longitude")
            dt_last = item.get("datetimeLast") or {}
            last_utc = dt_last.get("utc") if isinstance(dt_last, dict) else None

            # Filter: must be active recently
            if not (last_utc and last_utc >= cutoff_str):
                continue

            # Must measure target pollutants
            sensors = item.get("sensors", [])
            has_target_pols = any(
                s.get("parameter", {}).get("name") in target_pollutants
                for s in sensors
            )
            if not has_target_pols:
                continue

            if name and lat is not None and lon is not None:
                clean_name = name.strip()
                lat_f = float(lat)
                lon_f = float(lon)

                # Skip exact name duplicate or spatial duplicate (< 500 meters approx ~0.005 deg)
                is_duplicate = clean_name in seen_names or any(
                    abs(s["lat"] - lat_f) < 0.005 and abs(s["lon"] - lon_f) < 0.005
                    for s in stations
                )
                if not is_duplicate:
                    seen_names.add(clean_name)
                    stations.append({
                        "name": clean_name,
                        "lat": lat_f,
                        "lon": lon_f
                    })
                    if len(stations) >= target_count:
                        break

    return stations


def insert_stations_to_db(stations):
    """
    Insert station records into PostgreSQL stations table with PostGIS geography point.
    Uses ON CONFLICT (name) DO NOTHING to prevent duplicate station entries.
    """
    if not stations:
        print("No stations to insert.")
        return 0, 0

    ensure_db_schema()

    conn = get_db_connection()
    conn.autocommit = False
    cursor = conn.cursor()

    insert_query = """
        INSERT INTO stations (name, lat, lon, location)
        VALUES (%s, %s, %s, ST_MakePoint(%s, %s)::geography)
        ON CONFLICT (name) DO NOTHING
        RETURNING id;
    """

    inserted_count = 0
    skipped_count = 0
    try:
        for st in stations:
            cursor.execute(insert_query, (
                st["name"],
                st["lat"],
                st["lon"],
                st["lon"],
                st["lat"]
            ))
            res = cursor.fetchone()
            if res is not None:
                inserted_count += 1
            else:
                skipped_count += 1
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

    return inserted_count, skipped_count


def main():
    api_key = os.getenv("OPENAQ_API_KEY")
    if not api_key:
        print("Error: OPENAQ_API_KEY is not set in environment or backend/.env file.", file=sys.stderr)
        print("Please add 'OPENAQ_API_KEY=your_key_here' to your backend/.env file.", file=sys.stderr)
        sys.exit(1)

    try:
        stations = fetch_delhi_stations(api_key, target_count=14)
        if not stations:
            print("No monitoring stations found matching the criteria.")
            return

        print(f"\nTarget list of {len(stations)} active station(s) in Delhi NCR:")
        print("=" * 80)
        print(f"{'#':<4} {'Station Name':<50} {'Latitude':<12} {'Longitude':<12}")
        print("-" * 80)
        for i, st in enumerate(stations, start=1):
            print(f"{i:<4} {st['name']:<50} {st['lat']:<12.6f} {st['lon']:<12.6f}")
        print("=" * 80)

        inserted, skipped = insert_stations_to_db(stations)
        print(f"\nDatabase sync complete:")
        print(f"  - Rows newly inserted: {inserted}")
        print(f"  - Rows retained/skipped: {skipped}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
