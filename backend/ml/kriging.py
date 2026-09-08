"""
===================================================================================================
HawaGuide - Ordinary Kriging Spatial Interpolator & Park Air Quality Estimator
===================================================================================================

Module Overview:
----------------
This module implements geostatistical spatial interpolation using Ordinary Kriging (pykrige)
to estimate continuous air quality fields across Delhi NCR from discrete regulatory monitoring
stations. It provides inputs for the Park Environmental Vulnerability Index (PEVI) across 40
key urban green spaces.

===================================================================================================
KNOWN MATHEMATICAL LIMITATIONS & SPATIAL SMOOTHING TRADEOFF:
===================================================================================================
1. Linear Weighted-Average Constraint (Regression to the Mean):
   Ordinary Kriging estimates values at unmonitored locations as a linear combination of nearby
   observations: \\hat{Z}(x_0) = \\sum_{i=1}^n \\lambda_i Z(x_i), where \\sum \\lambda_i = 1.
   Because all weights sum to 1 and negative weights are either constrained or minimal, Kriging
   mathematically acts as a spatial smoothing operator (convex hull bounding). It CANNOT predict
   values higher than the local maximum or lower than the local minimum of surrounding stations.

2. Systematic Underestimation at Localized Pollution Hotspots:
   When an isolated emission hotspot (e.g. industrial zones, major transport corridors, waste burning)
   is surrounded by lower-concentration background stations, Kriging regresses the hotspot estimate
   toward the regional background mean.

3. Quantitative Empirical Validation (from 100-Timestamp Multi-Run LOOCV):
   Across 100 randomly sampled hourly timestamps from the 90-day archive (June-September 2026):
   - Overall Relative Error (LOOCV):
     * PM2.5: 54.7% (Mean RMSE: 25.88 ug/m3, Mean Actual: 44.78 ug/m3)
     * PM10:  49.0% (Mean RMSE: 61.65 ug/m3, Mean Actual: 133.17 ug/m3)
     * NO2:   75.2% (Mean RMSE: 22.12 ug/m3, Mean Actual: 29.31 ug/m3)
     * SO2:   69.0% (Mean RMSE: 13.15 ug/m3, Mean Actual: 18.62 ug/m3)
     * O3:    79.1% (Mean RMSE: 21.83 ug/m3, Mean Actual: 27.96 ug/m3)
     * CO:    67.1% (Mean RMSE: 0.56 mg/m3,  Mean Actual: 0.85 mg/m3)

   - Hotspot Underestimation Frequency:
     * PM2.5 Hotspots (Anand Vihar, NSIT Dwarka, Sirifort): 69.8% of timestamps underestimated.
     * PM10 Hotspots (Anand Vihar, Sector-125 Noida, Punjabi Bagh): 70.6% of timestamps underestimated.

   - Average Deficit during Peak Pollution Events:
     * PM2.5 Hotspots: Kriging predictions averaged +15.33 ug/m3 below ground-truth (up to 500+ ug/m3
       underestimated during localized spikes).
     * PM10 Hotspots: Kriging predictions averaged +56.09 ug/m3 below ground-truth (average 17.4%
       systematic underestimation deficit at hotspot monitors).

This spatial smoothing is an understood, mathematically intrinsic tradeoff of Gaussian random field
interpolation rather than an algorithmic flaw. In the HawaGuide pipeline, this smoothing provides
stable, continuous baseline air quality estimates across urban parks while avoiding runaway artifacts.
===================================================================================================
"""

import os
import sys
import random
import warnings
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from pykrige.ok import OrdinaryKriging
from dotenv import load_dotenv

# ─── Degenerate-Variogram Threshold ────────────────────────────────────────────
# When pykrige's auto-fit places >99% of variance in the nugget (partial_sill ≈ 0),
# the variogram is effectively pure-nugget and Kriging collapses to the global mean.
# We detect this and re-fit with nugget forced to 0 so spatial structure is attributed
# to the sill/range terms.
_NUGGET_DOMINANCE_THRESHOLD = 0.01   # partial_sill / total_sill must exceed this

# Suppress pandas SQL UserWarning
warnings.filterwarnings("ignore", category=UserWarning)

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

TARGET_POLLUTANTS = ["pm25", "pm10", "no2", "so2", "o3", "co"]

POLLUTANT_UNITS = {
    "pm25": "ug/m3",
    "pm10": "ug/m3",
    "no2": "ug/m3",
    "so2": "ug/m3",
    "o3": "ug/m3",
    "co": "mg/m3"
}

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
    {"name": "Town Park Faridabad", "lat": 28.3975, "lon": 77.3188, "zone": "Sector 12, Faridabad"},
    {"name": "Badkhal Lake Eco Park", "lat": 28.4145, "lon": 77.2835, "zone": "Faridabad"},
    {"name": "Surajkund Green Complex", "lat": 28.4872, "lon": 77.2831, "zone": "Faridabad / Delhi Border"},
    {"name": "Coronation Park", "lat": 28.7214, "lon": 77.1975, "zone": "Burari Road"}
]


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
    """Ensure interpolated_locations table exists in database."""
    conn = get_db_connection()
    conn.autocommit = True
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interpolated_locations (
                id BIGSERIAL PRIMARY KEY,
                location_name VARCHAR(255) NOT NULL,
                lat DOUBLE PRECISION NOT NULL,
                lon DOUBLE PRECISION NOT NULL,
                pollutant VARCHAR(50) NOT NULL,
                value DOUBLE PRECISION NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL,
                location geography(Point, 4326),
                CONSTRAINT uq_interp_loc_pollutant_ts UNIQUE (location_name, pollutant, timestamp)
            );
            CREATE INDEX IF NOT EXISTS idx_interp_loc_spatial ON interpolated_locations USING GIST (location);
            CREATE INDEX IF NOT EXISTS idx_interp_loc_ts ON interpolated_locations (timestamp);
            CREATE INDEX IF NOT EXISTS idx_interp_loc_name ON interpolated_locations (location_name);
        """)
    finally:
        cursor.close()
        conn.close()


def load_pollutant_readings(conn, pollutant: str):
    """
    Load all readings for a pollutant across all stations with coordinates.
    """
    query = """
        SELECT 
            r.timestamp,
            s.id AS station_id,
            s.name AS station_name,
            s.lat,
            s.lon,
            r.value
        FROM readings r
        JOIN stations s ON r.station_id = s.id
        WHERE r.pollutant = %s
        ORDER BY r.timestamp, s.id;
    """
    return pd.read_sql_query(query, conn, params=(pollutant,))


def fetch_recent_station_means(conn, pollutant: str, hours: int = 24):
    """
    Fetch the mean reading per station over the last `hours` hours of data.

    Using a time-windowed average instead of the single latest snapshot produces
    a more representative and spatially smooth concentration field for Kriging.
    A single hourly snapshot gives pykrige only ~14 points to fit 3 variogram
    parameters, which frequently yields degenerate variograms (range→0 or range→∞).
    Averaging across 24h readings smooths out transient spikes and gives a more
    reliable spatial signal.
    """
    query = """
        WITH latest AS (
            SELECT MAX(timestamp) AS max_ts FROM readings WHERE pollutant = %s
        )
        SELECT
            s.id AS station_id,
            s.name AS station_name,
            s.lat,
            s.lon,
            AVG(r.value) AS value,
            MAX(r.timestamp) AS timestamp
        FROM stations s
        JOIN readings r ON s.id = r.station_id
        JOIN latest ON TRUE
        WHERE r.pollutant = %s
          AND r.timestamp >= (latest.max_ts - INTERVAL '1 hour' * %s)
        GROUP BY s.id, s.name, s.lat, s.lon
        HAVING AVG(r.value) IS NOT NULL
        ORDER BY s.id;
    """
    return pd.read_sql_query(query, conn, params=(pollutant, pollutant, hours))


def fit_ok_robust(lons: np.ndarray, lats: np.ndarray, vals: np.ndarray,
                  variogram_model: str = "spherical") -> OrdinaryKriging:
    """
    Fit an OrdinaryKriging model with degenerate-variogram detection and recovery.

    pykrige's MLE-based auto-fit sometimes converges to a pure-nugget solution
    (partial_sill ≈ 0, nugget ≈ total variance) when the spatial autocorrelation
    signal is weak relative to the inter-station variance at a single timestamp.
    In that regime every park receives the same Kriging estimate (the station mean),
    erasing all spatial variation.

    Recovery strategy: if partial_sill < NUGGET_DOMINANCE_THRESHOLD × total_sill,
    re-fit with nugget forced to 0 and pass `weight=True` to emphasise short-lag
    pairs that carry the real spatial signal.
    """
    ok = OrdinaryKriging(
        lons, lats, vals,
        variogram_model=variogram_model,
        verbose=False,
        enable_plotting=False,
        weight=True,          # downweight pure-nugget solutions
    )
    vp = ok.variogram_model_parameters  # [nugget, partial_sill, range]
    total_sill = vp[0] + vp[1]
    nugget_dominated = (total_sill < 1e-10) or (vp[1] / total_sill < _NUGGET_DOMINANCE_THRESHOLD)

    if nugget_dominated:
        # Force nugget = 0; initialise psill = sample variance, range = half the domain diagonal
        sample_var = float(np.var(vals))
        lon_range = float(np.ptp(lons))
        lat_range = float(np.ptp(lats))
        domain_diag = float(np.hypot(lon_range, lat_range))
        forced_range = max(domain_diag * 0.5, 0.01)  # degrees
        forced_psill = max(sample_var, 1e-3)
        ok = OrdinaryKriging(
            lons, lats, vals,
            variogram_model=variogram_model,
            variogram_parameters={
                "nugget": 0.0,
                "psill":  forced_psill,
                "range":  forced_range,
            },
            verbose=False,
            enable_plotting=False,
            weight=True,
        )
    return ok


def evaluate_loocv_multi_timestamp(df: pd.DataFrame, pollutant: str, num_samples: int = 100, seed: int = 42):
    """
    Run Leave-One-Station-Out Cross-Validation (LOOCV) across randomly sampled timestamps.
    """
    min_stations_required = 6 if pollutant == "so2" else 10
    
    # Group observations by timestamp
    grouped = df.groupby("timestamp")
    valid_timestamps = [ts for ts, group in grouped if len(group) >= min_stations_required]
    
    total_valid = len(valid_timestamps)
    if total_valid == 0:
        raise ValueError(f"No timestamps found with >= {min_stations_required} reporting stations for {pollutant}.")
    
    sample_count = min(num_samples, total_valid)
    rng = random.Random(seed)
    sampled_ts = rng.sample(valid_timestamps, sample_count)

    run_rmses = []
    run_maes = []
    run_mean_actuals = []
    run_rel_errors = []
    station_counts = []
    
    all_predictions = []

    for ts in sampled_ts:
        group = grouped.get_group(ts)
        lons = group["lon"].to_numpy(dtype=float)
        lats = group["lat"].to_numpy(dtype=float)
        vals = group["value"].to_numpy(dtype=float)
        names = group["station_name"].to_list()
        
        n = len(vals)
        station_counts.append(n)
        
        ts_errors = []
        ts_abs_errors = []

        for i in range(n):
            test_lon = lons[i]
            test_lat = lats[i]
            actual_val = vals[i]
            station_name = names[i]

            train_mask = np.arange(n) != i
            train_lons = lons[train_mask]
            train_lats = lats[train_mask]
            train_vals = vals[train_mask]

            try:
                ok = fit_ok_robust(train_lons, train_lats, train_vals, variogram_model="spherical")
                z_pred, _ = ok.execute("points", [test_lon], [test_lat])
                pred_val = max(0.0, float(z_pred[0]))
            except Exception:
                pred_val = max(0.0, float(np.mean(train_vals)))

            err = pred_val - actual_val
            ts_errors.append(err)
            ts_abs_errors.append(abs(err))

            all_predictions.append({
                "timestamp": ts,
                "station_name": station_name,
                "actual": actual_val,
                "predicted": pred_val,
                "error": err,
                "abs_error": abs(err),
                "underestimation": actual_val - pred_val,
                "pollutant": pollutant
            })

        ts_errors_arr = np.array(ts_errors)
        ts_abs_errors_arr = np.array(ts_abs_errors)
        
        ts_rmse = np.sqrt(np.mean(ts_errors_arr ** 2))
        ts_mae = np.mean(ts_abs_errors_arr)
        ts_mean_val = np.mean(vals)
        ts_rel_err = (ts_rmse / ts_mean_val * 100.0) if ts_mean_val > 0 else 0.0

        run_rmses.append(ts_rmse)
        run_maes.append(ts_mae)
        run_mean_actuals.append(ts_mean_val)
        run_rel_errors.append(ts_rel_err)

    avg_rmse = float(np.mean(run_rmses))
    std_rmse = float(np.std(run_rmses))
    avg_mae = float(np.mean(run_maes))
    avg_mean_actual = float(np.mean(run_mean_actuals))
    avg_rel_err = float(np.mean(run_rel_errors))
    avg_stations = float(np.mean(station_counts))

    return {
        "pollutant": pollutant,
        "sample_count": sample_count,
        "total_available_ts": total_valid,
        "avg_stations": avg_stations,
        "avg_mean_actual": avg_mean_actual,
        "avg_rmse": avg_rmse,
        "std_rmse": std_rmse,
        "avg_mae": avg_mae,
        "avg_rel_err": avg_rel_err,
        "predictions": pd.DataFrame(all_predictions)
    }


def analyze_hotspot_underestimation(df_all_readings: pd.DataFrame, predictions_df: pd.DataFrame, pollutant: str, top_k: int = 3):
    """
    Analyze and display underestimation specifically at the top-K highest pollution stations.
    """
    unit = POLLUTANT_UNITS.get(pollutant, "ug/m3")
    
    station_avg = (
        df_all_readings.groupby("station_name")["value"]
        .agg(["mean", "max", "count"])
        .sort_values(by="mean", ascending=False)
    )
    hotspot_names = station_avg.head(top_k).index.tolist()

    hotspot_preds = predictions_df[predictions_df["station_name"].isin(hotspot_names)].copy()
    
    actuals = hotspot_preds["actual"].to_numpy()
    preds = hotspot_preds["predicted"].to_numpy()
    underestimations = actuals - preds
    
    pcts = np.where(actuals > 0, (underestimations / actuals) * 100.0, 0.0)
    hotspot_preds["pct_underestimated"] = pcts
    
    print("=" * 85)
    print(f"  HOTSPOT UNDERESTIMATION ANALYSIS: {pollutant.upper()} (Top {top_k} Highest-Pollution Stations)")
    print("=" * 85)
    print("Top Hotspot Stations (Historical Mean & Max):")
    for rank, h_name in enumerate(hotspot_names, 1):
        h_mean = station_avg.loc[h_name, "mean"]
        h_max = station_avg.loc[h_name, "max"]
        print(f"  {rank}. {h_name:<42} | Dataset Mean: {h_mean:6.2f} {unit} | Max: {h_max:6.2f} {unit}")
    
    print("\nSample Timestamps - Actual vs Kriging Predicted at Hotspot Stations:")
    print("-" * 85)
    print(f"{'Station Name':<35} {'Timestamp (IST)':<20} {'Actual':>8} {'Predicted':>10} {'Underest.':>10} {'% Drop':>8}")
    print("-" * 85)

    high_pollution_samples = hotspot_preds.sort_values(by="actual", ascending=False).head(8)
    
    for _, row in high_pollution_samples.iterrows():
        ts_str = str(row["timestamp"])[:19]
        act = row["actual"]
        pred = row["predicted"]
        under = row["underestimation"]
        pct = row["pct_underestimated"]
        print(f"{row['station_name'][:33]:<35} {ts_str:<20} {act:>8.1f} {pred:>10.1f} {under:>+10.1f} {pct:>7.1f}%")

    print("-" * 85)
    
    under_mask = hotspot_preds["actual"] > hotspot_preds["predicted"]
    under_pct_freq = (under_mask.sum() / len(hotspot_preds)) * 100.0
    mean_under_val = float(np.mean(underestimations))
    mean_under_pct = float(np.mean(pcts))
    
    print(f"Hotspot Statistical Summary across 100 Sample Timestamps:")
    print(f"  - Underestimation Frequency:  {under_pct_freq:.1f}% of timestamps underestimated by Kriging")
    print(f"  - Average Underestimation:    {mean_under_val:+.2f} {unit} (Kriging prediction was {abs(mean_under_val):.1f} {unit} below actual)")
    print(f"  - Average Relative Deficit:   {mean_under_pct:.1f}% below ground-truth at hotspot locations")
    print("=" * 85 + "\n")


def interpolate_parks_and_store(conn, variogram_model: str = "spherical"):
    """
    Interpolate current air quality pollutant values for 40 Delhi NCR parks
    using Ordinary Kriging and store the results in the interpolated_locations table.
    """
    ensure_db_schema()

    park_lons = np.array([p["lon"] for p in DELHI_NCR_PARKS], dtype=float)
    park_lats = np.array([p["lat"] for p in DELHI_NCR_PARKS], dtype=float)

    interpolated_rows = []
    summary_by_pollutant = {}

    for pollutant in TARGET_POLLUTANTS:
        df_latest = fetch_recent_station_means(conn, pollutant, hours=24)
        if len(df_latest) < 4:
            print(f"[-] Skipping {pollutant}: insufficient station readings ({len(df_latest)}).")
            continue

        st_lons = df_latest["lon"].to_numpy(dtype=float)
        st_lats = df_latest["lat"].to_numpy(dtype=float)
        st_vals = df_latest["value"].to_numpy(dtype=float)
        latest_ts = df_latest["timestamp"].max()

        try:
            ok = fit_ok_robust(st_lons, st_lats, st_vals, variogram_model=variogram_model)
            vp_fitted = ok.variogram_model_parameters
            total_sill = vp_fitted[0] + vp_fitted[1]
            nugget_pct = (vp_fitted[0] / total_sill * 100) if total_sill > 1e-10 else 100.0
            print(f"  [{pollutant.upper()}] Variogram — nugget={vp_fitted[0]:.3f}, "
                  f"psill={vp_fitted[1]:.3f}, range={vp_fitted[2]:.4f} "
                  f"(nugget {nugget_pct:.1f}% of total sill)")
            z_pred, _ = ok.execute("points", park_lons, park_lats)
            pred_vals = np.maximum(0.0, np.array(z_pred, dtype=float))
        except Exception as e:
            print(f"[-] Kriging fit failed for {pollutant}: {e}. Using mean fallback.")
            pred_vals = np.full(len(DELHI_NCR_PARKS), float(np.mean(st_vals)))

        for i, park in enumerate(DELHI_NCR_PARKS):
            val = float(pred_vals[i])
            interpolated_rows.append((
                park["name"],
                park["lat"],
                park["lon"],
                pollutant,
                round(val, 3),
                latest_ts,
                park["lon"],
                park["lat"]
            ))

        summary_by_pollutant[pollutant] = {
            "stations_used": len(df_latest),
            "mean_interp": float(np.mean(pred_vals)),
            "min_interp": float(np.min(pred_vals)),
            "max_interp": float(np.max(pred_vals)),
            "timestamp": str(latest_ts)
        }

    # Store into PostgreSQL database
    cursor = conn.cursor()
    insert_query = """
        INSERT INTO interpolated_locations (
            location_name, lat, lon, pollutant, value, timestamp, location
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, ST_MakePoint(%s, %s)::geography
        )
        ON CONFLICT (location_name, pollutant, timestamp) 
        DO UPDATE SET value = EXCLUDED.value, location = EXCLUDED.location
        RETURNING id;
    """

    inserted_count = 0
    try:
        for row in interpolated_rows:
            cursor.execute(insert_query, row)
            inserted_count += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

    return inserted_count, summary_by_pollutant


def main():
    print("=" * 85)
    print("      HAWAGUIDE ORDINARY KRIGING PIPELINE & PARK INTERPOLATION")
    print("=" * 85)
    print("Methodology: Leave-One-Station-Out Cross-Validation (LOOCV)")
    print("Variogram Model: Spherical")
    print("Sample Size: 100 randomly sampled timestamps per pollutant (Last 90 Days)\n")

    conn = get_db_connection()
    
    summary_results = []
    pm_predictions = {}
    pm_raw_dfs = {}

    for pollutant in TARGET_POLLUTANTS:
        unit = POLLUTANT_UNITS.get(pollutant, "")
        df = load_pollutant_readings(conn, pollutant)
        
        if df.empty:
            print(f"[-] {pollutant.upper()}: No readings found in database.")
            continue

        print(f"Evaluating {pollutant.upper():<5} across 100 sampled hourly timestamps...", flush=True)
        stats = evaluate_loocv_multi_timestamp(df, pollutant, num_samples=100, seed=42)
        
        if pollutant in ["pm25", "pm10"]:
            pm_predictions[pollutant] = stats["predictions"]
            pm_raw_dfs[pollutant] = df

        summary_results.append({
            "Pollutant": pollutant.upper(),
            "Sample Runs": stats["sample_count"],
            "Avg Stations": f"{stats['avg_stations']:.1f}",
            "Mean Actual": f"{stats['avg_mean_actual']:.2f} {unit}",
            "Mean RMSE": f"{stats['avg_rmse']:.2f} {unit}",
            "RMSE StdDev": f"+/-{stats['std_rmse']:.2f}",
            "Mean MAE": f"{stats['avg_mae']:.2f} {unit}",
            "Rel. Error": f"{stats['avg_rel_err']:.1f}%"
        })

    # Final 100-Run Summary Table
    print("\n" + "=" * 85)
    print("        FINAL 100-TIMESTAMP CROSS-VALIDATION STATISTICAL SUMMARY")
    print("=" * 85)
    summary_df = pd.DataFrame(summary_results)
    print(summary_df.to_string(index=False))
    print("=" * 85 + "\n")

    # Deep-dive Hotspot Underestimation Analysis for PM2.5 and PM10
    if "pm25" in pm_predictions:
        analyze_hotspot_underestimation(pm_raw_dfs["pm25"], pm_predictions["pm25"], "pm25", top_k=3)

    if "pm10" in pm_predictions:
        analyze_hotspot_underestimation(pm_raw_dfs["pm10"], pm_predictions["pm10"], "pm10", top_k=3)

    # Interpolate for 40 Real Delhi NCR Parks & Green Spaces
    print("=" * 85)
    print("  PEVI INPUT GENERATION: SPATIAL INTERPOLATION FOR 40 DELHI NCR PARKS")
    print("=" * 85)
    print(f"Interpolating air quality for {len(DELHI_NCR_PARKS)} green spaces across Delhi NCR...")
    
    inserted_rows, interp_summary = interpolate_parks_and_store(conn, variogram_model="spherical")
    
    print(f"\nSuccessfully stored {inserted_rows} interpolated reading records in 'interpolated_locations' table.\n")
    print("Summary of Interpolated Park Air Quality Estimates (Latest Snapshot):")
    print("-" * 85)
    print(f"{'Pollutant':<12} {'Stations Used':<15} {'Mean Estimate':<18} {'Min Est.':<15} {'Max Est.':<15}")
    print("-" * 85)
    for pol, p_data in interp_summary.items():
        u = POLLUTANT_UNITS.get(pol, "")
        print(f"{pol.upper():<12} {p_data['stations_used']:<15} {p_data['mean_interp']:<8.2f} {u:<8} {p_data['min_interp']:<6.2f} {u:<7} {p_data['max_interp']:<6.2f} {u:<7}")
    print("-" * 85)

    print("\nList of 40 Delhi NCR Parks / Green Spaces Configured:")
    print("=" * 85)
    print(f"{'#':<4} {'Park / Green Space Name':<38} {'Zone / Region':<28} {'Latitude':<10} {'Longitude':<10}")
    print("-" * 85)
    for idx, p in enumerate(DELHI_NCR_PARKS, start=1):
        print(f"{idx:<4} {p['name']:<38} {p['zone']:<28} {p['lat']:<10.4f} {p['lon']:<10.4f}")
    print("=" * 85)

    conn.close()


if __name__ == "__main__":
    main()
