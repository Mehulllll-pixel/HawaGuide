"""
===================================================================================================
HawaGuide — 1 to 6-Hour Ahead Multi-Horizon PM2.5 Forecaster (XGBoost v3 + PyTorch LSTM + Meteorology)
===================================================================================================

This module:
1. Ingests 1-year historical hourly PM2.5 readings & concurrent Open-Meteo weather observations.
2. Formulates multi-horizon change-relative-to-baseline targets for horizons h = 1..6:
       target_delta_h = PM2.5(t+h) - rolling_mean_24h(t)
3. Trains:
   - Multi-horizon XGBoost v3 Regressors (h = 1..6) with lags, trend, cyclical time, and weather at time t.
   - PyTorch LSTM Sequence Forecaster (12-hour lookback, multi-variate sequence -> 6-dim output vector).
4. Rigorously evaluates each individual horizon h = 1..6 and the 75/25 Ensemble:
   - Within-Station R² (station-mean-centered variance)
   - Naive Persistence Baseline (y_t -> y_t+h)
   - Pooled MAE, RMSE, R²
5. Persists models, weights, and scalers to backend/ml/models/.
===================================================================================================
"""

import os
import sys
import json
import random
import time
import warnings
from pathlib import Path
from typing import Tuple, Dict, Any, List
import joblib
import numpy as np
import pandas as pd
import psycopg2
import xgboost as xgb
from dotenv import load_dotenv
from sklearn.preprocessing import StandardScaler
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

# Set reproducible seeds
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(SEED)

warnings.filterwarnings("ignore", category=UserWarning)

# Paths setup
BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent
MODELS_DIR = BASE_DIR / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

for candidate in [BACKEND_DIR / ".env", PROJECT_ROOT / ".env", Path(".env")]:
    if candidate.is_file():
        load_dotenv(dotenv_path=candidate)
        break
else:
    load_dotenv()

SEQUENCE_LENGTH = 12  # 12-hour lookback window
HORIZONS = [1, 2, 3, 4, 5, 6]

XGB_FEATURE_COLUMNS = [
    "lag_1",
    "lag_2",
    "lag_3",
    "lag_6",
    "lag_24",
    "rolling_mean_6h",
    "rolling_mean_24h",
    "hour_of_day",
    "day_of_week",
    "recent_trend",
    "wind_speed",
    "wind_direction",
    "humidity",
    "precipitation",
    "temperature",
]

LSTM_FEATURE_COLUMNS = [
    "pm25",
    "wind_speed",
    "wind_dir_sin",
    "wind_dir_cos",
    "humidity",
    "precipitation",
    "temperature",
    "hour_sin",
    "hour_cos",
    "day_of_week_norm",
]


def calc_mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def calc_rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def calc_r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    return float(1.0 - (ss_res / ss_tot)) if ss_tot > 0 else 0.0


def calc_within_station_r2(df_eval: pd.DataFrame, actual_col: str, pred_col: str) -> float:
    ss_tot_within = 0.0
    ss_res_within = 0.0
    for _, group in df_eval.groupby("station_name"):
        act = group[actual_col].to_numpy()
        pred = group[pred_col].to_numpy()
        mean_act = float(np.mean(act))
        ss_tot_within += float(np.sum((act - mean_act) ** 2))
        ss_res_within += float(np.sum((act - pred) ** 2))
    return float(1.0 - (ss_res_within / ss_tot_within)) if ss_tot_within > 0 else 0.0


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


def load_raw_data(conn) -> Tuple[pd.DataFrame, pd.DataFrame]:
    pm_query = """
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
    df_pm = pd.read_sql_query(pm_query, conn)
    df_pm["timestamp"] = pd.to_datetime(df_pm["timestamp"])

    w_query = """
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
    df_w = pd.read_sql_query(w_query, conn)
    df_w["timestamp"] = pd.to_datetime(df_w["timestamp"])

    return df_pm, df_w


# =============================================================================
# PyTorch Model Architecture
# =============================================================================

class MultiHorizonLSTMForecaster(nn.Module):
    """
    1-Layer LSTM with projection head for multi-horizon (h=1..6) PM2.5 delta forecasting.
    """
    def __init__(self, input_dim: int = 10, hidden_dim: int = 32, num_layers: int = 1, output_dim: int = 6, dropout: float = 0.2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0
        )
        self.head = nn.Sequential(
            nn.Linear(hidden_dim, 16),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(16, output_dim)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        last_hidden = out[:, -1, :]
        return self.head(last_hidden)


# =============================================================================
# Data Engineering
# =============================================================================

def build_unified_dataset(df_pm: pd.DataFrame, df_w: pd.DataFrame) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """
    Build aligned tabular dataframe for XGBoost and sequence records for PyTorch LSTM.
    Both represent the exact same station time-series instances.
    """
    xgb_rows = []
    lstm_samples = []

    for st_id, group in df_pm.groupby("station_id"):
        st_name = group["station_name"].iloc[0]
        lat = group["lat"].iloc[0]
        lon = group["lon"].iloc[0]

        df_p = group.copy()
        df_p["hour_ts"] = df_p["timestamp"].dt.floor("h")
        df_p = df_p.groupby("hour_ts", as_index=False)["pm25"].mean().set_index("hour_ts").sort_index()

        full_idx = pd.date_range(start=df_p.index.min(), end=df_p.index.max(), freq="h")
        df_grid = df_p.reindex(full_idx)
        df_grid.index.name = "timestamp"

        # Interpolate minor gaps
        df_grid["pm25"] = df_grid["pm25"].interpolate(method="linear", limit=3)

        # Join weather
        st_w = df_w[df_w["station_id"] == st_id] if not df_w.empty else None
        if st_w is not None and not st_w.empty:
            df_w_clean = st_w.copy()
            df_w_clean["hour_ts"] = df_w_clean["timestamp"].dt.floor("h")
            df_w_clean = df_w_clean.groupby("hour_ts").first().reindex(full_idx)

            df_grid["wind_speed"] = df_w_clean["wind_speed"].interpolate(method="linear").bfill().ffill()
            df_grid["wind_direction"] = df_w_clean["wind_direction"].interpolate(method="linear").bfill().ffill()
            df_grid["humidity"] = df_w_clean["humidity"].interpolate(method="linear").bfill().ffill()
            df_grid["precipitation"] = df_w_clean["precipitation"].fillna(0.0)
            df_grid["temperature"] = df_w_clean["temperature"].interpolate(method="linear").bfill().ffill()
        else:
            for c in ["wind_speed", "wind_direction", "humidity", "precipitation", "temperature"]:
                df_grid[c] = 0.0

        # Lags & rolling means for XGBoost
        pm_s = df_grid["pm25"]
        df_grid["lag_1"] = pm_s.shift(1)
        df_grid["lag_2"] = pm_s.shift(2)
        df_grid["lag_3"] = pm_s.shift(3)
        df_grid["lag_6"] = pm_s.shift(6)
        df_grid["lag_24"] = pm_s.shift(24)
        df_grid["rolling_mean_6h"] = pm_s.rolling(window=6, min_periods=4).mean()
        df_grid["rolling_mean_24h"] = pm_s.rolling(window=24, min_periods=16).mean()
        df_grid["hour_of_day"] = df_grid.index.hour
        df_grid["day_of_week"] = df_grid.index.dayofweek
        df_grid["recent_trend"] = df_grid["lag_1"] - df_grid["lag_3"]

        # Cyclical for LSTM
        rad_wd = np.radians(df_grid["wind_direction"].to_numpy())
        df_grid["wind_dir_sin"] = np.sin(rad_wd)
        df_grid["wind_dir_cos"] = np.cos(rad_wd)
        hours = df_grid.index.hour.to_numpy()
        df_grid["hour_sin"] = np.sin(2.0 * np.pi * hours / 24.0)
        df_grid["hour_cos"] = np.cos(2.0 * np.pi * hours / 24.0)
        df_grid["day_of_week_norm"] = df_grid.index.dayofweek.to_numpy() / 6.0

        # Targets for h=1..6
        for h in HORIZONS:
            df_grid[f"future_pm25_{h}h"] = pm_s.shift(-h)
            df_grid[f"target_delta_{h}h"] = df_grid[f"future_pm25_{h}h"] - df_grid["rolling_mean_24h"]

        # Drop NaNs
        req_xgb_cols = XGB_FEATURE_COLUMNS + ["rolling_mean_24h"] + [f"future_pm25_{h}h" for h in HORIZONS] + [f"target_delta_{h}h" for h in HORIZONS]
        valid_mask = ~df_grid[req_xgb_cols].isna().any(axis=1)

        feature_matrix = df_grid[LSTM_FEATURE_COLUMNS].to_numpy()
        delta_targets = df_grid[[f"target_delta_{h}h" for h in HORIZONS]].to_numpy()
        future_pm_targets = df_grid[[f"future_pm25_{h}h" for h in HORIZONS]].to_numpy()
        rolling_24h_arr = df_grid["rolling_mean_24h"].to_numpy()
        lag1_arr = df_grid["lag_1"].to_numpy()
        timestamps = df_grid.index

        n_rows = len(df_grid)
        for i in range(SEQUENCE_LENGTH - 1, n_rows - max(HORIZONS)):
            if not valid_mask.iloc[i]:
                continue
            
            seq_feat = feature_matrix[i - SEQUENCE_LENGTH + 1 : i + 1]
            if np.isnan(seq_feat).any():
                continue

            ts = timestamps[i]
            
            # Tabular row
            row_dict = {
                "timestamp": ts,
                "station_id": st_id,
                "station_name": st_name,
                "lat": lat,
                "lon": lon,
                "rolling_mean_24h": rolling_24h_arr[i],
                "current_pm25": lag1_arr[i],
            }
            for col in XGB_FEATURE_COLUMNS:
                row_dict[col] = df_grid[col].iloc[i]
            for h in HORIZONS:
                row_dict[f"future_pm25_{h}h"] = future_pm_targets[i, h - 1]
                row_dict[f"target_delta_{h}h"] = delta_targets[i, h - 1]
            
            xgb_rows.append(row_dict)

            # Sequence sample
            lstm_samples.append({
                "timestamp": ts,
                "station_id": st_id,
                "station_name": st_name,
                "seq": seq_feat.astype(np.float32),
                "target_deltas": delta_targets[i].astype(np.float32),
                "future_pm25": future_pm_targets[i].astype(np.float32),
                "baseline_24h": float(rolling_24h_arr[i]),
                "current_pm25": float(lag1_arr[i]),
            })

    df_xgb = pd.DataFrame(xgb_rows).sort_values(by="timestamp").reset_index(drop=True)
    return df_xgb, lstm_samples


# =============================================================================
# Training Procedures
# =============================================================================

def train_xgboost_models(df_train: pd.DataFrame) -> Dict[int, xgb.XGBRegressor]:
    """Train distinct XGBoost regressors for each forecast horizon h = 1..6."""
    models = {}
    X_train = df_train[XGB_FEATURE_COLUMNS]

    for h in HORIZONS:
        y_train = df_train[f"target_delta_{h}h"]
        model = xgb.XGBRegressor(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.03,
            subsample=0.85,
            colsample_bytree=0.85,
            min_child_weight=3,
            gamma=0.1,
            reg_alpha=0.05,
            reg_lambda=1.0,
            random_state=SEED + h,
            n_jobs=-1,
            objective="reg:squarederror"
        )
        model.fit(X_train, y_train)
        models[h] = model
    return models


def train_lstm_model(X_train_scaled: np.ndarray, y_train_raw: np.ndarray,
                     epochs: int = 25, batch_size: int = 128, lr: float = 0.005) -> MultiHorizonLSTMForecaster:
    """Train the PyTorch MultiHorizon LSTM model using robust SmoothL1Loss on delta targets."""
    class SeqDataset(Dataset):
        def __init__(self, X, y):
            self.X = torch.tensor(X, dtype=torch.float32)
            self.y = torch.tensor(y, dtype=torch.float32)

        def __len__(self):
            return len(self.X)

        def __getitem__(self, idx):
            return self.X[idx], self.y[idx]

    loader = DataLoader(SeqDataset(X_train_scaled, y_train_raw), batch_size=batch_size, shuffle=True)
    input_dim = X_train_scaled.shape[2]
    model = MultiHorizonLSTMForecaster(input_dim=input_dim, hidden_dim=32, num_layers=1, output_dim=len(HORIZONS), dropout=0.2)
    criterion = nn.SmoothL1Loss(beta=5.0)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    model.train()
    print(f"  Training PyTorch Multi-Horizon LSTM ({epochs} epochs, {len(X_train_scaled):,} sequences)...", flush=True)

    for epoch in range(1, epochs + 1):
        total_loss = 0.0
        n_b = 0
        for bx, by in loader:
            optimizer.zero_grad()
            out = model(bx)
            loss = criterion(out, by)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            total_loss += loss.item()
            n_b += 1
        scheduler.step()
        if epoch % 5 == 0 or epoch == epochs:
            print(f"    Epoch [{epoch:2d}/{epochs}] - Loss (SmoothL1 delta): {total_loss / max(1, n_b):.4f}", flush=True)

    return model


# =============================================================================
# Evaluation & Benchmarking across all 6 horizons
# =============================================================================

def evaluate_models_on_test_set(
    xgb_models: Dict[int, xgb.XGBRegressor],
    lstm_model: MultiHorizonLSTMForecaster,
    df_test: pd.DataFrame,
    test_lstm_samples: List[Dict],
    scaler_X: StandardScaler
) -> Dict[str, Any]:
    """
    Evaluates XGBoost, LSTM, and 75/25 Ensemble across each horizon h = 1..6:
    - Within-station R² (station-mean-centered)
    - Persistence baseline (y_t -> y_{t+h})
    - Pooled MAE, RMSE, R²
    """
    # 1. XGBoost predictions
    X_test_xgb = df_test[XGB_FEATURE_COLUMNS]
    xgb_preds_pm25 = {}
    for h in HORIZONS:
        pred_delta = xgb_models[h].predict(X_test_xgb)
        xgb_preds_pm25[h] = np.maximum(5.0, pred_delta + df_test["rolling_mean_24h"].to_numpy())

    # 2. LSTM predictions
    X_test_raw = np.array([s["seq"] for s in test_lstm_samples])
    N, L, F = X_test_raw.shape
    X_test_scaled = scaler_X.transform(X_test_raw.reshape(-1, F)).reshape(N, L, F)

    lstm_model.eval()
    with torch.no_grad():
        preds_delta_lstm = lstm_model(torch.tensor(X_test_scaled, dtype=torch.float32)).numpy()

    baseline_arr = np.array([s["baseline_24h"] for s in test_lstm_samples])
    lstm_preds_pm25 = {}
    for idx, h in enumerate(HORIZONS):
        lstm_preds_pm25[h] = np.maximum(5.0, preds_delta_lstm[:, idx] + baseline_arr)

    # 3. 75/25 Ensemble predictions
    ensemble_preds_pm25 = {}
    for h in HORIZONS:
        ensemble_preds_pm25[h] = 0.75 * xgb_preds_pm25[h] + 0.25 * lstm_preds_pm25[h]

    # Benchmarks per horizon
    horizon_metrics = []
    station_names = df_test["station_name"].to_numpy()

    for h in HORIZONS:
        y_true = df_test[f"future_pm25_{h}h"].to_numpy()
        y_persist = df_test["current_pm25"].to_numpy()

        df_eval_h = pd.DataFrame({
            "station_name": station_names,
            "y_true": y_true,
            "y_persist": y_persist,
            "y_xgb": xgb_preds_pm25[h],
            "y_lstm": lstm_preds_pm25[h],
            "y_ens": ensemble_preds_pm25[h],
        })

        # Persistence
        p_mae = calc_mae(y_true, y_persist)
        p_rmse = calc_rmse(y_true, y_persist)
        p_r2_pooled = calc_r2(y_true, y_persist)
        p_r2_within = calc_within_station_r2(df_eval_h, "y_true", "y_persist")

        # XGBoost
        xgb_mae = calc_mae(y_true, xgb_preds_pm25[h])
        xgb_rmse = calc_rmse(y_true, xgb_preds_pm25[h])
        xgb_r2_pooled = calc_r2(y_true, xgb_preds_pm25[h])
        xgb_r2_within = calc_within_station_r2(df_eval_h, "y_true", "y_xgb")

        # LSTM
        lstm_mae = calc_mae(y_true, lstm_preds_pm25[h])
        lstm_rmse = calc_rmse(y_true, lstm_preds_pm25[h])
        lstm_r2_pooled = calc_r2(y_true, lstm_preds_pm25[h])
        lstm_r2_within = calc_within_station_r2(df_eval_h, "y_true", "y_lstm")

        # 75/25 Ensemble
        ens_mae = calc_mae(y_true, ensemble_preds_pm25[h])
        ens_rmse = calc_rmse(y_true, ensemble_preds_pm25[h])
        ens_r2_pooled = calc_r2(y_true, ensemble_preds_pm25[h])
        ens_r2_within = calc_within_station_r2(df_eval_h, "y_true", "y_ens")

        horizon_metrics.append({
            "horizon": h,
            # Persistence
            "persist_mae": p_mae,
            "persist_rmse": p_rmse,
            "persist_r2_pooled": p_r2_pooled,
            "persist_r2_within": p_r2_within,
            # XGBoost
            "xgb_mae": xgb_mae,
            "xgb_rmse": xgb_rmse,
            "xgb_r2_pooled": xgb_r2_pooled,
            "xgb_r2_within": xgb_r2_within,
            # LSTM
            "lstm_mae": lstm_mae,
            "lstm_rmse": lstm_rmse,
            "lstm_r2_pooled": lstm_r2_pooled,
            "lstm_r2_within": lstm_r2_within,
            # Ensemble 75/25
            "ens_mae": ens_mae,
            "ens_rmse": ens_rmse,
            "ens_r2_pooled": ens_r2_pooled,
            "ens_r2_within": ens_r2_within,
        })

    return {
        "horizon_metrics": horizon_metrics,
        "n_test": len(df_test)
    }


def print_evaluation_report(results: Dict[str, Any], split_cutoff: pd.Timestamp):
    metrics = results["horizon_metrics"]
    print("\n" + "=" * 120)
    print("      HAWAGUIDE MULTI-HORIZON (1h to 6h) PM2.5 ENSEMBLE FORECASTING BENCHMARK REPORT")
    print("=" * 120)
    print(f"Chronological Test Boundary: >= {str(split_cutoff)[:19]} UTC  ({results['n_test']:,} test records per horizon)")
    print(f"Ensemble Formula: 0.75 * XGBoost_v3(t+h) + 0.25 * PyTorch_LSTM(t+h)\n")

    print("-" * 120)
    print(f"{'Horizon':<8} | {'Persistence Baseline':<28} | {'XGBoost v3':<25} | {'PyTorch LSTM':<25} | {'75/25 Ensemble':<25}")
    print(f"{'':<8} | {'MAE':>7} {'RMSE':>7} {'WithinR2':>10} | {'MAE':>7} {'RMSE':>7} {'WithinR2':>8} | {'MAE':>7} {'RMSE':>7} {'WithinR2':>8} | {'MAE':>7} {'RMSE':>7} {'WithinR2':>8}")
    print("-" * 120)

    for m in metrics:
        h = m["horizon"]
        print(
            f"t+{h}h (hr {h}) | "
            f"{m['persist_mae']:>6.2f}u {m['persist_rmse']:>6.2f}u {m['persist_r2_within']:>+10.3f} | "
            f"{m['xgb_mae']:>6.2f}u {m['xgb_rmse']:>6.2f}u {m['xgb_r2_within']:>+8.3f} | "
            f"{m['lstm_mae']:>6.2f}u {m['lstm_rmse']:>6.2f}u {m['lstm_r2_within']:>+8.3f} | "
            f"{m['ens_mae']:>6.2f}u {m['ens_rmse']:>6.2f}u {m['ens_r2_within']:>+8.3f}"
        )
    print("-" * 120)

    # Summary of Pooled vs Within R2 for 75/25 ensemble
    print("\n" + "=" * 120)
    print("                   75/25 ENSEMBLE COMPREHENSIVE HORIZON-BY-HORIZON BREAKDOWN")
    print("=" * 120)
    print(f"{'Horizon':<12} {'Ensemble MAE':>14} {'Ensemble RMSE':>15} {'Pooled R^2':>14} {'Within-Station R^2':>22} {'vs Persistence MAE':>22}")
    print("-" * 120)
    for m in metrics:
        h = m["horizon"]
        mae_imp = ((m["persist_mae"] - m["ens_mae"]) / m["persist_mae"]) * 100.0
        print(
            f"t+{h} hour{'s' if h>1 else ' ':>4} "
            f"{m['ens_mae']:>12.2f} ug/m3 "
            f"{m['ens_rmse']:>13.2f} ug/m3 "
            f"{m['ens_r2_pooled']:>14.3f} "
            f"{m['ens_r2_within']:>+20.3f}   "
            f"{mae_imp:>+19.1f}% improvement"
        )
    print("=" * 120 + "\n")


# =============================================================================
# Main Pipeline
# =============================================================================

def main():
    print("=" * 90)
    print("  HAWAGUIDE MULTI-HORIZON PM2.5 FORECASTER: TRAINING, PERSISTENCE & VERIFICATION")
    print("=" * 90)

    conn = get_db_connection()
    try:
        t0 = time.time()
        print("\n[1/5] Extracting 1-year PM2.5 time-series and Open-Meteo weather data...", flush=True)
        df_pm, df_w = load_raw_data(conn)
        print(f"      [+] Loaded {len(df_pm):,} PM2.5 readings across {df_pm['station_id'].nunique()} stations.")
        print(f"      [+] Loaded {len(df_w):,} weather records.")

        print("\n[2/5] Constructing multi-horizon target deltas and regularized sequence arrays...", flush=True)
        df_xgb, lstm_samples = build_unified_dataset(df_pm, df_w)
        print(f"      [+] Total aligned instances: {len(df_xgb):,} samples across Delhi NCR.")

        # Strict chronological split: last 15 days test
        max_time = df_xgb["timestamp"].max()
        split_cutoff = max_time - pd.Timedelta(days=15)

        train_mask = df_xgb["timestamp"] < split_cutoff
        df_train = df_xgb[train_mask].copy().reset_index(drop=True)
        df_test = df_xgb[~train_mask].copy().reset_index(drop=True)

        train_lstm_samples = [s for s in lstm_samples if s["timestamp"] < split_cutoff]
        test_lstm_samples = [s for s in lstm_samples if s["timestamp"] >= split_cutoff]

        print(f"      [+] Chronological split: {len(df_train):,} train instances, {len(df_test):,} test instances.")
        print(f"      [+] Cutoff boundary: {split_cutoff}")

        # Scalers for LSTM
        X_train_raw = np.array([s["seq"] for s in train_lstm_samples])
        y_train_raw = np.array([s["target_deltas"] for s in train_lstm_samples])

        N, L, F = X_train_raw.shape
        scaler_X = StandardScaler()
        scaler_X.fit(X_train_raw.reshape(-1, F))

        X_train_scaled = scaler_X.transform(X_train_raw.reshape(-1, F)).reshape(N, L, F)

        print("\n[3/5] Training Multi-Horizon XGBoost Regressors (h = 1..6)...", flush=True)
        t_xgb = time.time()
        xgb_models = train_xgboost_models(df_train)
        print(f"      [+] All 6 XGBoost models trained in {time.time() - t_xgb:.2f}s.")

        print("\n[4/5] Training PyTorch Multi-Horizon LSTM Sequence Model...", flush=True)
        t_lstm = time.time()
        lstm_model = train_lstm_model(X_train_scaled, y_train_raw, epochs=25, batch_size=128, lr=0.005)
        print(f"      [+] PyTorch LSTM trained in {time.time() - t_lstm:.2f}s.")

        print("\n[5/5] Evaluating all horizons (Within-Station R² + Persistence benchmark)...", flush=True)
        eval_results = evaluate_models_on_test_set(
            xgb_models, lstm_model, df_test, test_lstm_samples, scaler_X
        )
        print_evaluation_report(eval_results, split_cutoff)

        # ---------------------------------------------------------------------
        # Persist Artifacts
        # ---------------------------------------------------------------------
        print("Saving trained artifacts to backend/ml/models/...")
        
        # 1. XGBoost models
        xgb_path = MODELS_DIR / "xgboost_forecast_v3.joblib"
        joblib.dump(xgb_models, xgb_path)
        print(f"  [+] Saved XGBoost models -> {xgb_path}")

        # 2. PyTorch LSTM state dict
        lstm_path = MODELS_DIR / "lstm_forecast_v3.pt"
        torch.save(lstm_model.state_dict(), lstm_path)
        print(f"  [+] Saved LSTM state dict -> {lstm_path}")

        # 3. Scalers
        scalers_path = MODELS_DIR / "lstm_scalers.joblib"
        joblib.dump({"scaler_X": scaler_X}, scalers_path)
        print(f"  [+] Saved Scalers -> {scalers_path}")

        # 4. Metadata JSON
        meta_path = MODELS_DIR / "model_metadata.json"
        metadata = {
            "model_type": "75% XGBoost v3 + 25% PyTorch LSTM Multi-Horizon Forecaster",
            "horizons": HORIZONS,
            "xgb_feature_columns": XGB_FEATURE_COLUMNS,
            "lstm_feature_columns": LSTM_FEATURE_COLUMNS,
            "sequence_length": SEQUENCE_LENGTH,
            "ensemble_weights": {"xgboost": 0.75, "lstm": 0.25},
            "train_samples": len(df_train),
            "test_samples": len(df_test),
            "split_cutoff": str(split_cutoff),
            "evaluation_metrics": eval_results["horizon_metrics"],
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        }
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)
        print(f"  [+] Saved Model Metadata -> {meta_path}")

        print(f"\n[OK] Whole training, verification, and persistence pipeline completed in {time.time() - t0:.1f}s.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
