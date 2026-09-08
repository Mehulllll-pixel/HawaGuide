"""
===================================================================================================
HawaGuide - 6-Hour Ahead PM2.5 Hourly Forecasting Engine (XGBoost v3 + Meteorological Features)
===================================================================================================

Module Overview:
----------------
This module builds, trains, and evaluates a gradient-boosted regression model (XGBoost) to predict
station-level PM2.5 concentrations 6 hours into the future (t+6) across Delhi NCR monitoring stations.

Methodology:
------------
1. Data Extraction & Regularization:
   - Ingests hourly PM2.5 time-series from the 'readings' table across all monitoring stations.
   - Reindexes each station onto a continuous 1-hour temporal grid to prevent irregular-lag distortion.
   - Ingests concurrent meteorological observations from the 'weather' table (Open-Meteo Archive).

2. Feature Engineering (Per-Station Time-Series):
   - Autoregressive Lags: t-1, t-2, t-3, t-6, t-24 hours.
   - Rolling Window Statistics: 6-hour rolling mean, 24-hour rolling mean.
   - Cyclical / Temporal Indicators: Hour-of-day (0-23), Day-of-week (0-6).
   - Short-term Rate of Change (Recent Trend): lag_1 minus lag_3 (velocity proxy).
   - Meteorological Features at prediction time t:
       * wind_speed: 10m wind speed (km/h) - atmospheric dispersion & transport
       * wind_direction: 10m wind direction (degrees) - upwind pollution advection
       * humidity: 2m relative humidity (%) - hygroscopic growth & aerosol formation
       * precipitation: Rain (mm) - wet scavenging / washout effect
       * temperature: 2m temperature (°C) - surface heating & boundary layer proxy

3. Change-Relative-to-Baseline Target (v2/v3):
   - Instead of predicting raw PM2.5 at t+6, the model predicts the DEVIATION from the
     current 24-hour rolling mean:
         target_delta_6h = PM2.5(t+6) - rolling_mean_24h(t)
   - Motivation: The 24h rolling mean captures each station's current baseline level. By
     subtracting it from the target, the model is forced to learn genuine short-term
     temporal dynamics rather than just memorising which stations run high vs low.
   - At inference, predictions are back-transformed to original PM2.5 scale:
         predicted_PM2.5(t+6) = predicted_delta + rolling_mean_24h(t)

4. Chronological Time-Series Validation (Zero Lookahead Leakage):
   - Strict chronological split: Training on the first 75 days, Testing on the final 15 days.
   - Shuffling is strictly disallowed to prevent future information leakage into historical trees.

5. Performance Benchmarking & Feature Attribution:
   - Reports Test MAE, RMSE, R^2, and compares against a naive Persistence Baseline (t -> t+6).
   - Reports within-station R^2 using station-centered residuals (vs v2 baseline of -0.133).
   - Evaluates Feature Importances (Gain, Weight) to inspect whether weather features provide signal.
===================================================================================================
"""

import os
import sys
import warnings
from pathlib import Path
from typing import Tuple, Dict, Any, List
import numpy as np
import pandas as pd
import psycopg2
import xgboost as xgb
from dotenv import load_dotenv

def calc_mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))

def calc_rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))

def calc_r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    return float(1.0 - (ss_res / ss_tot)) if ss_tot > 0 else 0.0


# Suppress warnings
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


# =============================================================================
# Feature columns used by the XGBoost model (v3: Lags + Trend + Weather).
# =============================================================================
FEATURE_COLUMNS = [
    # Autoregressive Lags & Rolling Statistics
    "lag_1",
    "lag_2",
    "lag_3",
    "lag_6",
    "lag_24",
    "rolling_mean_6h",
    "rolling_mean_24h",
    # Temporal Indicators & Trend
    "hour_of_day",
    "day_of_week",
    "recent_trend",        # v2: lag_1 - lag_3  (velocity)
    # Meteorological Features at time t (v3)
    "wind_speed",          # Open-Meteo wind_speed_10m (km/h)
    "wind_direction",      # Open-Meteo wind_direction_10m (degrees)
    "humidity",            # Open-Meteo relative_humidity_2m (%)
    "precipitation",       # Open-Meteo precipitation (mm)
    "temperature",         # Open-Meteo temperature_2m (°C)
]

# v2/v3 Target formulation: Model predicts deviation from current 24h rolling mean
TARGET_COLUMN = "target_delta_6h"    # PM2.5(t+6) - rolling_mean_24h(t)
BASELINE_COLUMN = "rolling_mean_24h" # Used for back-transformation


def get_db_connection():
    """Establish and return a connection to the PostgreSQL database."""
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


def load_raw_pm25_readings(conn) -> pd.DataFrame:
    """
    Load all PM2.5 readings with station metadata from PostgreSQL.
    """
    query = """
        SELECT 
            r.timestamp,
            s.id AS station_id,
            s.name AS station_name,
            s.lat,
            s.lon,
            r.value AS pm25
        FROM readings r
        JOIN stations s ON r.station_id = s.id
        WHERE r.pollutant = 'pm25'
        ORDER BY s.id, r.timestamp;
    """
    df = pd.read_sql_query(query, conn)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def load_weather_data(conn) -> pd.DataFrame:
    """
    Load all meteorological observations from the 'weather' table.
    """
    query = """
        SELECT 
            station_id,
            timestamp,
            wind_speed,
            wind_direction,
            humidity,
            precipitation,
            temperature
        FROM weather
        ORDER BY station_id, timestamp;
    """
    df_w = pd.read_sql_query(query, conn)
    df_w["timestamp"] = pd.to_datetime(df_w["timestamp"])
    return df_w


def build_station_features(df_station: pd.DataFrame, df_weather_station: pd.DataFrame = None) -> pd.DataFrame:
    """
    Construct time-series lags, rolling means, temporal features, recent trend,
    joined meteorological variables at time t, and the CHANGE-RELATIVE-TO-BASELINE
    6-hour ahead target for a single station.

    Target (v2/v3):
        target_delta_6h = PM2.5(t+6) - rolling_mean_24h(t)

    Back-transformation at inference:
        predicted_PM2.5(t+6) = predicted_delta + rolling_mean_24h(t)
    """
    st_id = df_station["station_id"].iloc[0]
    st_name = df_station["station_name"].iloc[0]
    lat = df_station["lat"].iloc[0]
    lon = df_station["lon"].iloc[0]

    # Floor timestamps to the nearest hour and deduplicate
    df_st = df_station.copy()
    df_st["hour_ts"] = df_st["timestamp"].dt.floor("h")
    df_st = df_st.groupby("hour_ts", as_index=False)["pm25"].mean()

    # Set datetime index
    df_st = df_st.set_index("hour_ts").sort_index()

    # Create continuous hourly index across the station's span
    full_idx = pd.date_range(start=df_st.index.min(), end=df_st.index.max(), freq="h")
    df_reindexed = df_st.reindex(full_idx)
    df_reindexed.index.name = "timestamp"

    # Fill tiny gaps (up to 2 consecutive missing hours) via linear interpolation
    pm_series = df_reindexed["pm25"].interpolate(method="linear", limit=2)

    # 1. Autoregressive Lags (t-1, t-2, t-3, t-6, t-24)
    feat_df = pd.DataFrame(index=df_reindexed.index)
    feat_df["current_pm25"] = pm_series
    feat_df["lag_1"] = pm_series.shift(1)
    feat_df["lag_2"] = pm_series.shift(2)
    feat_df["lag_3"] = pm_series.shift(3)
    feat_df["lag_6"] = pm_series.shift(6)
    feat_df["lag_24"] = pm_series.shift(24)

    # 2. Rolling Means (preceding 6h and 24h, min_periods ensuring robust coverage)
    feat_df["rolling_mean_6h"] = pm_series.rolling(window=6, min_periods=4).mean()
    feat_df["rolling_mean_24h"] = pm_series.rolling(window=24, min_periods=16).mean()

    # 3. Temporal Indicators
    feat_df["hour_of_day"] = feat_df.index.hour
    feat_df["day_of_week"] = feat_df.index.dayofweek

    # 4. Recent Trend / Velocity (v2 addition)
    feat_df["recent_trend"] = feat_df["lag_1"] - feat_df["lag_3"]

    # 5. Meteorological Features at time t (v3 addition)
    if df_weather_station is not None and not df_weather_station.empty:
        df_w_clean = df_weather_station.copy()
        df_w_clean["hour_ts"] = df_w_clean["timestamp"].dt.floor("h")
        df_w_clean = df_w_clean.groupby("hour_ts").first()
        
        weather_cols = ["wind_speed", "wind_direction", "humidity", "precipitation", "temperature"]
        for col in weather_cols:
            if col in df_w_clean.columns:
                feat_df[col] = df_w_clean[col].reindex(feat_df.index)
                if col == "precipitation":
                    feat_df[col] = feat_df[col].fillna(0.0)
                else:
                    feat_df[col] = feat_df[col].interpolate(method="linear").bfill().ffill()
            else:
                feat_df[col] = 0.0
    else:
        # Fallback if no weather data present
        for col in ["wind_speed", "wind_direction", "humidity", "precipitation", "temperature"]:
            feat_df[col] = 0.0

    # 6. Future raw PM2.5 value (needed for back-transformed evaluation)
    feat_df["future_pm25_6h"] = pm_series.shift(-6)

    # 7. Target Variable (v2/v3): DEVIATION from current 24h rolling mean
    feat_df["target_delta_6h"] = feat_df["future_pm25_6h"] - feat_df["rolling_mean_24h"]

    # Station metadata
    feat_df["station_id"] = st_id
    feat_df["station_name"] = st_name
    feat_df["lat"] = lat
    feat_df["lon"] = lon

    # Drop rows with NaN in target or any essential feature columns
    required_cols = FEATURE_COLUMNS + [TARGET_COLUMN, "future_pm25_6h", BASELINE_COLUMN]
    feat_df = feat_df.dropna(subset=required_cols).reset_index()

    return feat_df


def prepare_dataset(conn) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    """
    Extract, engineer features, join weather, and perform strict chronological train/test split.
    """
    df_raw = load_raw_pm25_readings(conn)
    if df_raw.empty:
        raise ValueError("No PM2.5 records found in 'readings' table. Ingest data first.")

    df_weather = load_weather_data(conn)
    if df_weather.empty:
        print("  [!] WARNING: 'weather' table is empty. Running without weather observations.")

    station_groups = df_raw.groupby("station_id")
    station_dfs = []

    for st_id, group in station_groups:
        st_weather = df_weather[df_weather["station_id"] == st_id] if not df_weather.empty else None
        st_features = build_station_features(group, st_weather)
        if len(st_features) > 50:
            station_dfs.append(st_features)

    df_all = pd.concat(station_dfs, ignore_index=True)
    df_all = df_all.sort_values(by="timestamp").reset_index(drop=True)

    # Chronological Split: 75 days train, last 15 days test
    max_time = df_all["timestamp"].max()
    split_cutoff = max_time - pd.Timedelta(days=15)

    df_train = df_all[df_all["timestamp"] < split_cutoff].copy().reset_index(drop=True)
    df_test = df_all[df_all["timestamp"] >= split_cutoff].copy().reset_index(drop=True)

    return df_train, df_test, split_cutoff


def train_xgboost_forecaster(df_train: pd.DataFrame) -> xgb.XGBRegressor:
    """
    Train XGBoost Regressor on the engineered historical features.
    The model predicts target_delta_6h = PM2.5(t+6) - rolling_mean_24h(t).
    """
    X_train = df_train[FEATURE_COLUMNS]
    y_train = df_train[TARGET_COLUMN]

    model = xgb.XGBRegressor(
        n_estimators=350,
        max_depth=6,
        learning_rate=0.03,
        subsample=0.85,
        colsample_bytree=0.85,
        min_child_weight=3,
        gamma=0.1,
        reg_alpha=0.05,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=-1,
        objective="reg:squarederror"
    )

    model.fit(X_train, y_train)
    return model


def evaluate_forecast(model: xgb.XGBRegressor, df_test: pd.DataFrame) -> Dict[str, Any]:
    """
    Evaluate 6-hour forecast on the test set.

    Back-transformation:
        pred_delta   = model.predict(X_test)           [target_delta_6h scale]
        pred_pm25    = pred_delta + rolling_mean_24h   [original PM2.5 scale]

    R^2 metrics reported:
        - r2_pooled:  Standard R^2 on back-transformed PM2.5 predictions vs actual.
        - r2_within:  R^2 computed on station-mean-centered residuals -- measures only
                      genuine within-station temporal skill, not between-station ranking.
        - r2_between: R^2 on station cross-sectional means.
    """
    X_test = df_test[FEATURE_COLUMNS]
    y_test_raw = df_test["future_pm25_6h"].to_numpy()         # Ground truth (original scale)
    baseline = df_test[BASELINE_COLUMN].to_numpy()             # rolling_mean_24h at prediction time

    # Model predicts the delta; back-transform to original PM2.5 scale
    pred_delta = model.predict(X_test)
    y_pred = np.maximum(0.0, pred_delta + baseline)

    # Naive Persistence Baseline: predict t+6 == current t (lag_1)
    y_persistence = df_test["lag_1"].to_numpy()

    # -------------------------------------------------------------------------
    # Overall Pooled Metrics (original PM2.5 scale)
    # -------------------------------------------------------------------------
    mae = calc_mae(y_test_raw, y_pred)
    rmse = calc_rmse(y_test_raw, y_pred)
    r2_pooled = calc_r2(y_test_raw, y_pred)
    mean_actual = float(np.mean(y_test_raw))
    rel_error = (rmse / mean_actual * 100.0) if mean_actual > 0 else 0.0

    # Persistence Baseline Metrics
    p_mae = calc_mae(y_test_raw, y_persistence)
    p_rmse = calc_rmse(y_test_raw, y_persistence)
    p_r2 = calc_r2(y_test_raw, y_persistence)

    # -------------------------------------------------------------------------
    # Within-Station & Between-Station Variance Decomposition
    # -------------------------------------------------------------------------
    y_bar_global = float(np.mean(y_test_raw))
    ss_tot_pooled = float(np.sum((y_test_raw - y_bar_global) ** 2))

    ss_tot_within = 0.0
    ss_res_within = 0.0

    df_eval = df_test.copy()
    df_eval["pred_pm25"] = y_pred
    df_eval["actual_pm25"] = y_test_raw
    df_eval["abs_err"] = np.abs(y_test_raw - y_pred)
    df_eval["sq_err"] = (y_test_raw - y_pred) ** 2

    station_metrics = []
    for st_name, group in df_eval.groupby("station_name"):
        st_actual = group["actual_pm25"].to_numpy()
        st_pred = group["pred_pm25"].to_numpy()
        st_mean = float(np.mean(st_actual))
        st_pred_mean = float(np.mean(st_pred))
        st_bias = st_pred_mean - st_mean

        st_ss_tot = float(np.sum((st_actual - st_mean) ** 2))
        st_ss_res = float(np.sum((st_actual - st_pred) ** 2))

        ss_tot_within += st_ss_tot
        ss_res_within += st_ss_res

        st_mae = calc_mae(st_actual, st_pred)
        st_rmse = calc_rmse(st_actual, st_pred)
        st_r2 = float(1.0 - (st_ss_res / st_ss_tot)) if st_ss_tot > 0 else 0.0
        st_rel = (st_rmse / st_mean * 100.0) if st_mean > 0 else 0.0

        station_metrics.append({
            "station_name": st_name,
            "test_samples": len(group),
            "mean_actual": st_mean,
            "mean_pred": st_pred_mean,
            "bias": st_bias,
            "std_actual": float(np.std(st_actual)),
            "mae": st_mae,
            "rmse": st_rmse,
            "rel_error": st_rel,
            "r2": st_r2
        })

    r2_within = float(1.0 - (ss_res_within / ss_tot_within)) if ss_tot_within > 0 else 0.0

    # Between-Station R^2 (weighted by station sample counts)
    df_st_means = df_eval.groupby("station_name").agg(
        actual_mean=("actual_pm25", "mean"),
        pred_mean=("pred_pm25", "mean"),
        count=("actual_pm25", "count")
    )
    weights = df_st_means["count"].to_numpy()
    act_means = df_st_means["actual_mean"].to_numpy()
    prd_means = df_st_means["pred_mean"].to_numpy()

    ss_between_tot = float(np.sum(weights * (act_means - y_bar_global) ** 2))
    ss_between_res = float(np.sum(weights * (act_means - prd_means) ** 2))
    r2_between = float(1.0 - (ss_between_res / ss_between_tot)) if ss_between_tot > 0 else 0.0

    # -------------------------------------------------------------------------
    # Delta-scale metrics (on the model's direct output -- the deviation from baseline)
    # -------------------------------------------------------------------------
    y_delta_true = df_test[TARGET_COLUMN].to_numpy()
    delta_mae = calc_mae(y_delta_true, pred_delta)
    delta_rmse = calc_rmse(y_delta_true, pred_delta)
    delta_r2 = calc_r2(y_delta_true, pred_delta)

    # -------------------------------------------------------------------------
    # Feature Importance Extraction
    # -------------------------------------------------------------------------
    booster = model.get_booster()
    importance_gain = booster.get_score(importance_type="gain")
    importance_weight = booster.get_score(importance_type="weight")
    total_gain = sum(importance_gain.values()) if importance_gain else 1.0

    feature_importances = []
    for f in FEATURE_COLUMNS:
        gain = importance_gain.get(f, 0.0)
        weight = importance_weight.get(f, 0.0)
        gain_pct = (gain / total_gain * 100.0) if total_gain > 0 else 0.0
        feature_importances.append({
            "feature": f,
            "gain": gain,
            "gain_pct": gain_pct,
            "weight": weight
        })

    feature_importances.sort(key=lambda x: x["gain"], reverse=True)

    return {
        # Original-scale metrics
        "mae": mae,
        "rmse": rmse,
        "r2_pooled": r2_pooled,
        "r2_within": r2_within,
        "r2_between": r2_between,
        "ss_tot_pooled": ss_tot_pooled,
        "ss_tot_within": ss_tot_within,
        "ss_between_tot": ss_between_tot,
        "mean_actual": mean_actual,
        "rel_error": rel_error,
        # Persistence baseline
        "persistence_mae": p_mae,
        "persistence_rmse": p_rmse,
        "persistence_r2": p_r2,
        # Delta-scale (model's direct output space)
        "delta_mae": delta_mae,
        "delta_rmse": delta_rmse,
        "delta_r2": delta_r2,
        # Station-level breakdown and feature importances
        "station_metrics": pd.DataFrame(station_metrics).sort_values(by="r2"),
        "feature_importances": feature_importances,
        "total_test_samples": len(df_test)
    }


def print_forecast_report(df_train: pd.DataFrame, df_test: pd.DataFrame,
                          split_cutoff: pd.Timestamp, results: Dict[str, Any]):
    """
    Print comprehensive terminal evaluation report with:
      - Model v3 vs Persistence Baseline (original PM2.5 scale)
      - Delta-scale diagnostic (model's direct prediction space)
      - Within/Between R^2 decomposition (comparison against v2 within-station R^2 = -0.133)
      - Feature importances (highlighting weather feature utility)
      - Per-station evaluation breakdown
    """
    print("\n" + "=" * 110)
    print("        HAWAGUIDE 6-HOUR AHEAD PM2.5 XGBOOST FORECASTING REPORT  (v3 Weather + Change-Target)")
    print("=" * 110)
    print(f"Target (v2/v3):  target_delta_6h = PM2.5(t+6) - rolling_mean_24h(t)")
    print(f"                 => Back-transformed: pred_PM2.5(t+6) = pred_delta + rolling_mean_24h(t)")
    print(f"Weather Features: wind_speed, wind_direction, humidity, precipitation, temperature (at time t)")
    print(f"Chronological Split: Training (First 75 Days) | Testing (Last 15 Days)")
    print(f"Split Date Boundary: {str(split_cutoff)[:19]} UTC")
    print(f"Training Sample Count: {len(df_train):,} rows across stations")
    print(f"Testing Sample Count:  {len(df_test):,} rows across stations\n")

    # 1. Original-Scale Model vs Baseline Comparison
    print("-" * 110)
    print("               MODEL PERFORMANCE VS NAIVE PERSISTENCE BASELINE  [original PM2.5 ug/m3 scale]")
    print("-" * 110)
    print(f"{'Model / Estimator':<42} {'Test MAE':>12} {'Test RMSE':>12} {'Rel. Error':>12} {'Pooled R^2':>12}")
    print("-" * 110)
    print(
        f"{'XGBoost v3 (weather + change-target)':<42} "
        f"{results['mae']:>10.2f} ug/m3 "
        f"{results['rmse']:>10.2f} ug/m3 "
        f"{results['rel_error']:>11.1f}% "
        f"{results['r2_pooled']:>12.3f}"
    )
    p_rel = (results['persistence_rmse'] / results['mean_actual'] * 100) if results['mean_actual'] > 0 else 0.0
    print(
        f"{'Naive Persistence (y_t -> y_t+6)':<42} "
        f"{results['persistence_mae']:>10.2f} ug/m3 "
        f"{results['persistence_rmse']:>10.2f} ug/m3 "
        f"{p_rel:>11.1f}% "
        f"{results['persistence_r2']:>12.3f}"
    )
    print("-" * 110)
    mae_improvement = ((results['persistence_mae'] - results['mae']) / results['persistence_mae']) * 100.0
    rmse_improvement = ((results['persistence_rmse'] - results['rmse']) / results['persistence_rmse']) * 100.0
    print(f"XGBoost v3 Improvement over Baseline:  {mae_improvement:+.1f}% MAE  |  {rmse_improvement:+.1f}% RMSE\n")

    # 2. Delta-Scale Diagnostics (model's direct prediction space)
    print("=" * 110)
    print("           DELTA-SCALE DIAGNOSTICS  [model's direct output: target_delta_6h]")
    print("=" * 110)
    print(f"  MAE  on delta  =  {results['delta_mae']:>7.2f} ug/m3  (how well the model predicts the deviation from baseline)")
    print(f"  RMSE on delta  =  {results['delta_rmse']:>7.2f} ug/m3")
    print(f"  R^2  on delta  =  {results['delta_r2']:>+7.4f}")
    print("=" * 110 + "\n")

    # 3. Panel Variance & R^2 Decomposition (Within vs Between)
    print("=" * 110)
    print("          PANEL VARIANCE DECOMPOSITION: WITHIN-STATION VS BETWEEN-STATION R^2  [original scale]")
    print("=" * 110)
    pct_within = (results['ss_tot_within'] / results['ss_tot_pooled']) * 100.0
    pct_between = (results['ss_between_tot'] / results['ss_tot_pooled']) * 100.0
    print(f"Total Test Set Variance (SS_tot_pooled):     {results['ss_tot_pooled']:14,.1f}  (100.0%)")
    print(f"  |-- Within-Station Variance (SS_within):   {results['ss_tot_within']:14,.1f}  ({pct_within:5.1f}% of total variance)")
    print(f"  \\-- Between-Station Variance (SS_between): {results['ss_between_tot']:14,.1f}  ({pct_between:5.1f}% of total variance)")
    print("-" * 110)
    print(f"{'R-Squared Metric':<55} {'R^2 Value':>10}   {'Interpretation'}")
    print("-" * 110)
    print(f"{'1. Pooled R^2 (back-transformed to original scale):':<55} {results['r2_pooled']:>+10.4f}   Captures both spatial baselines + temporal trends")
    print(f"{'2. Between-Station R^2 (spatial cross-section):':<55} {results['r2_between']:>+10.4f}   How well model ranks stations by baseline pollution")
    print(f"{'3. Within-Station R^2 (station-mean centered):':<55} {results['r2_within']:>+10.4f}   Pure temporal forecasting skill (vs v2: -0.133)")
    print("-" * 110)
    print("Historical Progression:")
    print("  - v1 (Raw Target, Lags only):           Within-Station R^2 = -0.108  | Pooled R^2 = +0.313")
    print("  - v2 (Change Target, Lags + Trend):      Within-Station R^2 = -0.133  | Pooled R^2 = +0.298")
    print(f"  - v3 (Change Target + Weather at t):    Within-Station R^2 = {results['r2_within']:>+6.3f}  | Pooled R^2 = {results['r2_pooled']:>+6.3f}")
    print("=" * 110 + "\n")

    # 4. Feature Importances
    print("=" * 110)
    print("                    XGBOOST FEATURE IMPORTANCE BREAKDOWN  (v3 Feature Set with Weather)")
    print("=" * 110)
    print(f"{'Rank':<5} {'Feature Name':<20} {'Category':<14} {'Gain Importance':>16} {'Gain %':>10} {'Splits':>8}")
    print("-" * 110)

    categories = {
        "lag_1": "Lag / Autoreg",
        "lag_2": "Lag / Autoreg",
        "lag_3": "Lag / Autoreg",
        "lag_6": "Lag / Autoreg",
        "lag_24": "Lag / Autoreg",
        "rolling_mean_6h": "Rolling Avg",
        "rolling_mean_24h": "Baseline Avg",
        "hour_of_day": "Temporal",
        "day_of_week": "Temporal",
        "recent_trend": "Trend / Velocity",
        "wind_speed": "Weather / Met",
        "wind_direction": "Weather / Met",
        "humidity": "Weather / Met",
        "precipitation": "Weather / Met",
        "temperature": "Weather / Met",
    }

    for idx, fi in enumerate(results["feature_importances"], start=1):
        f_name = fi["feature"]
        cat = categories.get(f_name, "Other")
        # Highlight weather features
        marker = " [MET]" if cat == "Weather / Met" else ""
        print(f"{idx:<5} {f_name + marker:<20} {cat:<14} {fi['gain']:>16.2f} {fi['gain_pct']:>9.1f}% {int(fi['weight']):>8}")
    print("-" * 110)

    # Weather feature contribution summary
    weather_gain_pct = sum(fi["gain_pct"] for fi in results["feature_importances"] if categories.get(fi["feature"]) == "Weather / Met")
    print(f"Total Combined Meteorological Feature Gain Share: {weather_gain_pct:.1f}%\n")

    # 5. Per-Station Evaluation Breakdown
    print("=" * 110)
    print("                  PER-STATION 6-HOUR AHEAD TEST EVALUATION BREAKDOWN  [original PM2.5 scale]")
    print("=" * 110)
    print(f"{'#':<4} {'Station Name':<38} {'N':>4} {'MeanAct':>8} {'MeanPred':>9} {'Bias':>7} {'StdAct':>7} {'RMSE':>7} {'R^2':>7}")
    print("-" * 110)

    df_st = results["station_metrics"]
    for idx, (_, r) in enumerate(df_st.iterrows(), start=1):
        print(
            f"{idx:<4} "
            f"{r['station_name'][:36]:<38} "
            f"{int(r['test_samples']):>4} "
            f"{r['mean_actual']:>7.1f}u "
            f"{r['mean_pred']:>8.1f}u "
            f"{r['bias']:>+6.1f}u "
            f"{r['std_actual']:>6.1f}u "
            f"{r['rmse']:>6.1f}u "
            f"{r['r2']:>+7.3f}"
        )
    print("-" * 110 + "\n")


def main():
    print("=" * 90)
    print("      HAWAGUIDE PM2.5 6-HOUR FORECASTER TRAINING & EVALUATION  (v3 Weather + Change-Target)")
    print("=" * 90)

    conn = get_db_connection()
    try:
        print("Extracting hourly PM2.5 time-series and joining meteorological observations...", flush=True)
        df_train, df_test, split_cutoff = prepare_dataset(conn)
        print(f"[+] Dataset prepared: {len(df_train):,} training records, {len(df_test):,} testing records.")
        print(f"    Features ({len(FEATURE_COLUMNS)}): {', '.join(FEATURE_COLUMNS)}")
        print(f"    Target: target_delta_6h = PM2.5(t+6) - rolling_mean_24h(t)  [change-relative-to-baseline]")

        print(f"\nTraining XGBoost Regressor (350 trees, max_depth=6, lr=0.03, {len(FEATURE_COLUMNS)} features)...", flush=True)
        model = train_xgboost_forecaster(df_train)
        print("[+] Training completed successfully.")

        print("\nEvaluating 6-hour ahead predictions across the 15-day holdout test set...", flush=True)
        results = evaluate_forecast(model, df_test)

        print_forecast_report(df_train, df_test, split_cutoff, results)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
