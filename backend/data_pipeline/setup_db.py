import os
import sys
from pathlib import Path
import psycopg2
from psycopg2 import sql
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


def setup_database():
    print("Connecting to PostgreSQL database...")
    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()

    # Read schema.sql from data_pipeline directory
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    print("Applying schema and enabling PostGIS extension...")
    cursor.execute(schema_sql)
    print("Schema applied successfully.\n")

    # Confirm PostGIS Extension
    print("=== PostGIS Extension Status ===")
    cursor.execute("SELECT extname, extversion FROM pg_extension WHERE extname = 'postgis';")
    ext = cursor.fetchone()
    if ext:
        print(f"PostGIS is ENABLED (Version: {ext[1]})")
        cursor.execute("SELECT PostGIS_Full_Version();")
        print(f"Full version details: {cursor.fetchone()[0]}\n")
    else:
        print("PostGIS is NOT enabled!\n")

    # Inspect Tables and Columns
    print("=== Database Schema Details ===")
    for table_name in ["stations", "readings"]:
        print(f"\nTable: {table_name}")
        cursor.execute("""
            SELECT column_name, data_type, udt_name, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = %s AND table_schema = 'public'
            ORDER BY ordinal_position;
        """, (table_name,))
        columns = cursor.fetchall()
        for col in columns:
            print(f"  - {col[0]}: {col[1]} (type: {col[2]}), nullable: {col[3]}, default: {col[4]}")

    # Inspect Indexes
    print("\n=== Indexes Created ===")
    cursor.execute("""
        SELECT tablename, indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'public' AND tablename IN ('stations', 'readings')
        ORDER BY tablename, indexname;
    """)
    indexes = cursor.fetchall()
    for idx in indexes:
        print(f"  - [{idx[0]}] {idx[1]}: {idx[2]}")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    try:
        setup_database()
    except Exception as e:
        print(f"Error setting up database: {e}", file=sys.stderr)
        sys.exit(1)
