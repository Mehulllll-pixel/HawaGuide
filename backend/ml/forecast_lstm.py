"""
===================================================================================================
HawaGuide - 6-Hour Ahead PM2.5 Sequence Forecaster (PyTorch LSTM + Meteorology)
===================================================================================================

Module Overview:
----------------
This module builds, trains, and evaluates a deep recurrent neural network (LSTM) to predict
station-level PM2.5 concentrations 6 hours ahead (t+6) across Delhi NCR monitoring stations.

Architecture & Formulation:
---------------------------
1. Sequence Window:
   - Ingests continuous historical sequences of length L=24 hours (t-23 to t) per station.
   - At each timestep in the sequence, the model consumes:
       * pm25: Continuous station PM2.5 observation (ug/m3)
       * wind_speed: 10m wind speed (km/h)
       * wind_dir_sin, wind_dir_cos: Circularly decomposed 10m wind direction
       * humidity: 2m relative humidity (%)
       * precipitation: Hourly precipitation (mm)
       * temperature: 2m air temperature (°C)
       * hour_sin, hour_cos: Diurnal cycle trigonometric encoding
       * day_of_week: Day of week normalized

2. Change-Relative-to-Baseline Target:
   - Same formulation as XGBoost v2/v3:
         target_delta_6h = PM2.5(t+6) - rolling_mean_24h(t)
   - Predictions back-transformed to original PM2.5 scale:
         predicted_PM2.5(t+6) = predicted_delta + rolling_mean_24h(t)

3. Deep Learning Architecture:
   - 2-Layer LSTM with hidden dimension 64, recurrent dropout 0.2
   - Fully connected projection head with ReLU non-linearity and dropout
   - Trained using AdamW optimizer with learning rate scheduler and early checkpointing

4. Chronological Validation (Zero Lookahead Leakage):
   - Strict chronological split: First 75 days for training, Final 15 days for testing.
   - Feature scalers fitted strictly on training data only.

5. Comprehensive Benchmarking:
   - Reports Original-Scale MAE, RMSE, Pooled R^2, and Within-Station R^2.
   - Full per-station evaluation breakdown compared directly with XGBoost v3 and Persistence.
===================================================================================================
"""

import os
import sys
import random
import warnings
from pathlib import Path
from typing import Tuple, Dict, Any, List
import numpy as np
import pandas as pd
import psycopg2
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

# Search and load .env
BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

for candidate in [BACKEND_DIR / ".env", PROJECT_ROOT / ".env", Path(".env")]:
    if candidate.is_file():
        load_dotenv(dotenv_path=candidate)
        break
else:
    load_dotenv()

SEQUENCE_LENGTH = 12  # 12-hour lookback window (t-11 to t)
FORECAST_HORIZON = 6  # 6-hour ahead prediction (t+6)

FEATURE_COLS = [
    "pm25",
    "wind_speed",
    "wind_dir_sin",
    "wind_dir_cos",
    "humidity",
    "precipitation",
    "temperature",
    "hour_sin",
    "hour_cos",
    "day_of_week",
]


def calc_mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))

def calc_rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))

def calc_r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    return float(1.0 - (ss_res / ss_tot)) if ss_tot > 0 else 0.0


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


def load_raw_data(conn) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load PM2.5 readings and weather table from PostgreSQL."""
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


def build_station_sequence_dataset(df_pm_st: pd.DataFrame, df_w_st: pd.DataFrame,
                                   seq_len: int = 12, horizon: int = 6) -> List[Dict[str, Any]]:
    """
    Construct continuous time-series grid and sliding windows for a single station.
    """
    st_id = df_pm_st["station_id"].iloc[0]
    st_name = df_pm_st["station_name"].iloc[0]
    lat = df_pm_st["lat"].iloc[0]
    lon = df_pm_st["lon"].iloc[0]

    # Floor timestamps to hour
    df_p = df_pm_st.copy()
    df_p["hour_ts"] = df_p["timestamp"].dt.floor("h")
    df_p = df_p.groupby("hour_ts", as_index=False)["pm25"].mean().set_index("hour_ts").sort_index()

    # Create continuous hourly index
    full_idx = pd.date_range(start=df_p.index.min(), end=df_p.index.max(), freq="h")
    df_grid = df_p.reindex(full_idx)
    df_grid.index.name = "timestamp"

    # Fill minor gaps
    df_grid["pm25"] = df_grid["pm25"].interpolate(method="linear", limit=3)

    # Join weather
    if df_w_st is not None and not df_w_st.empty:
        df_w_clean = df_w_st.copy()
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

    # Trigonometric cyclical features
    rad_wd = np.radians(df_grid["wind_direction"].to_numpy())
    df_grid["wind_dir_sin"] = np.sin(rad_wd)
    df_grid["wind_dir_cos"] = np.cos(rad_wd)

    hours = df_grid.index.hour.to_numpy()
    df_grid["hour_sin"] = np.sin(2.0 * np.pi * hours / 24.0)
    df_grid["hour_cos"] = np.cos(2.0 * np.pi * hours / 24.0)
    df_grid["day_of_week"] = df_grid.index.dayofweek.to_numpy() / 6.0

    # 24-hour rolling mean at each timestep (baseline anchor)
    df_grid["rolling_mean_24h"] = df_grid["pm25"].rolling(window=24, min_periods=16).mean()

    # Shift for future target
    df_grid["future_pm25_6h"] = df_grid["pm25"].shift(-horizon)
    df_grid["target_delta_6h"] = df_grid["future_pm25_6h"] - df_grid["rolling_mean_24h"]

    # Extract sequences
    feature_matrix = df_grid[FEATURE_COLS].to_numpy()
    rolling_24h_arr = df_grid["rolling_mean_24h"].to_numpy()
    future_pm25_arr = df_grid["future_pm25_6h"].to_numpy()
    target_delta_arr = df_grid["target_delta_6h"].to_numpy()
    timestamps = df_grid.index

    samples = []
    n_rows = len(df_grid)

    for i in range(seq_len - 1, n_rows - horizon):
        # Sequence spans [i - seq_len + 1 : i + 1]
        seq_feat = feature_matrix[i - seq_len + 1 : i + 1]
        
        # Check for NaNs
        if np.isnan(seq_feat).any():
            continue
        
        target_delta = target_delta_arr[i]
        future_pm25 = future_pm25_arr[i]
        baseline_24h = rolling_24h_arr[i]
        curr_pm25 = feature_matrix[i, 0]  # pm25 at prediction time t

        if np.isnan(target_delta) or np.isnan(future_pm25) or np.isnan(baseline_24h):
            continue

        pred_timestamp = timestamps[i]

        samples.append({
            "seq": seq_feat.astype(np.float32),
            "target_delta": float(target_delta),
            "future_pm25": float(future_pm25),
            "baseline_24h": float(baseline_24h),
            "curr_pm25": float(curr_pm25),
            "timestamp": pred_timestamp,
            "station_id": st_id,
            "station_name": st_name,
            "lat": lat,
            "lon": lon,
        })

    return samples


class TimeSeriesSequenceDataset(Dataset):
    """PyTorch Dataset for multi-variate sliding sequence windows."""
    def __init__(self, X: np.ndarray, y: np.ndarray):
        self.X = torch.tensor(X, dtype=torch.float32)
        self.y = torch.tensor(y, dtype=torch.float32)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return self.X[idx], self.y[idx]


class LSTMForecaster(nn.Module):
    """
    1-Layer Recurrent Neural Network (LSTM) with Dropout regularization for change-target PM2.5 forecasting.
    """
    def __init__(self, input_dim: int, hidden_dim: int = 32, num_layers: int = 1, dropout: float = 0.25):
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
            nn.Linear(16, 1)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        last_hidden = out[:, -1, :]  # Take final hidden state of sequence
        pred = self.head(last_hidden)
        return pred.squeeze(-1)


def prepare_datasets(conn) -> Tuple[List[Dict], List[Dict], pd.Timestamp, StandardScaler, StandardScaler]:
    """
    Ingest, build sliding sequences, apply strict chronological split, and scale features.
    """
    df_pm, df_w = load_raw_data(conn)
    if df_pm.empty:
        raise ValueError("No PM2.5 readings found in database.")

    all_samples = []
    for st_id, group in df_pm.groupby("station_id"):
        st_w = df_w[df_w["station_id"] == st_id] if not df_w.empty else None
        st_samples = build_station_sequence_dataset(group, st_w, seq_len=SEQUENCE_LENGTH, horizon=FORECAST_HORIZON)
        all_samples.extend(st_samples)

    df_meta = pd.DataFrame([{"timestamp": s["timestamp"]} for s in all_samples])
    max_time = df_meta["timestamp"].max()
    split_cutoff = max_time - pd.Timedelta(days=15)

    train_samples = [s for s in all_samples if s["timestamp"] < split_cutoff]
    test_samples = [s for s in all_samples if s["timestamp"] >= split_cutoff]

    # Fit Scalers strictly on training data
    X_train_raw = np.array([s["seq"] for s in train_samples])  # (N_train, 24, n_feat)
    y_train_raw = np.array([s["target_delta"] for s in train_samples])  # (N_train,)

    N_train, L, F = X_train_raw.shape
    scaler_X = StandardScaler()
    scaler_X.fit(X_train_raw.reshape(-1, F))

    scaler_y = StandardScaler()
    scaler_y.fit(y_train_raw.reshape(-1, 1))

    return train_samples, test_samples, split_cutoff, scaler_X, scaler_y


def transform_data(samples: List[Dict], scaler_X: StandardScaler, scaler_y: StandardScaler) -> Tuple[np.ndarray, np.ndarray]:
    """Apply fitted Scalers to sequence matrices and targets."""
    X_raw = np.array([s["seq"] for s in samples])
    y_raw = np.array([s["target_delta"] for s in samples])

    N, L, F = X_raw.shape
    X_scaled = scaler_X.transform(X_raw.reshape(-1, F)).reshape(N, L, F)
    y_scaled = scaler_y.transform(y_raw.reshape(-1, 1)).flatten()

    return X_scaled, y_scaled


def train_lstm_model(X_train: np.ndarray, y_train: np.ndarray,
                     epochs: int = 35, batch_size: int = 128, lr: float = 0.003) -> LSTMForecaster:
    """Train the PyTorch LSTM Forecaster."""
    dataset = TimeSeriesSequenceDataset(X_train, y_train)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    input_dim = X_train.shape[2]
    model = LSTMForecaster(input_dim=input_dim, hidden_dim=32, num_layers=1, dropout=0.25)
    criterion = nn.MSELoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    model.train()
    print(f"Training LSTM ({epochs} epochs, batch_size={batch_size}, lr={lr})...", flush=True)

    for epoch in range(1, epochs + 1):
        total_loss = 0.0
        n_batches = 0
        for bx, by in loader:
            optimizer.zero_grad()
            pred = model(bx)
            loss = criterion(pred, by)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            total_loss += loss.item()
            n_batches += 1

        scheduler.step()
        if epoch % 5 == 0 or epoch == epochs:
            avg_loss = total_loss / max(1, n_batches)
            print(f"  Epoch [{epoch:2d}/{epochs}] - Loss (MSE scaled): {avg_loss:.4f}", flush=True)

    return model


def evaluate_lstm_forecast(model: LSTMForecaster, test_samples: List[Dict],
                           scaler_X: StandardScaler, scaler_y: StandardScaler) -> Dict[str, Any]:
    """
    Evaluate LSTM predictions on the 15-day holdout test set.
    """
    X_test_scaled, _ = transform_data(test_samples, scaler_X, scaler_y)

    model.eval()
    with torch.no_grad():
        preds_scaled = model(torch.tensor(X_test_scaled, dtype=torch.float32)).numpy()

    # Inverse transform predictions back to delta scale
    preds_delta = scaler_y.inverse_transform(preds_scaled.reshape(-1, 1)).flatten()

    y_test_raw = np.array([s["future_pm25"] for s in test_samples])
    baseline_24h = np.array([s["baseline_24h"] for s in test_samples])
    y_persistence = np.array([s["curr_pm25"] for s in test_samples])

    # Back-transform delta to original PM2.5 scale
    y_pred = np.maximum(0.0, preds_delta + baseline_24h)

    # Pooled Metrics
    mae = calc_mae(y_test_raw, y_pred)
    rmse = calc_rmse(y_test_raw, y_pred)
    r2_pooled = calc_r2(y_test_raw, y_pred)
    mean_actual = float(np.mean(y_test_raw))
    rel_error = (rmse / mean_actual * 100.0) if mean_actual > 0 else 0.0

    # Persistence Baseline
    p_mae = calc_mae(y_test_raw, y_persistence)
    p_rmse = calc_rmse(y_test_raw, y_persistence)
    p_r2 = calc_r2(y_test_raw, y_persistence)

    # Panel Variance & Within-Station Decomposition
    y_bar_global = float(np.mean(y_test_raw))
    ss_tot_pooled = float(np.sum((y_test_raw - y_bar_global) ** 2))

    ss_tot_within = 0.0
    ss_res_within = 0.0

    df_eval = pd.DataFrame({
        "station_name": [s["station_name"] for s in test_samples],
        "actual_pm25": y_test_raw,
        "pred_pm25": y_pred,
    })

    station_metrics = []
    for st_name, group in df_eval.groupby("station_name"):
        st_act = group["actual_pm25"].to_numpy()
        st_prd = group["pred_pm25"].to_numpy()
        st_mean = float(np.mean(st_act))
        st_prd_mean = float(np.mean(st_prd))
        st_bias = st_prd_mean - st_mean

        st_ss_tot = float(np.sum((st_act - st_mean) ** 2))
        st_ss_res = float(np.sum((st_act - st_prd) ** 2))

        ss_tot_within += st_ss_tot
        ss_res_within += st_ss_res

        st_mae = calc_mae(st_act, st_prd)
        st_rmse = calc_rmse(st_act, st_prd)
        st_r2 = float(1.0 - (st_ss_res / st_ss_tot)) if st_ss_tot > 0 else 0.0

        station_metrics.append({
            "station_name": st_name,
            "test_samples": len(group),
            "mean_actual": st_mean,
            "mean_pred": st_prd_mean,
            "bias": st_bias,
            "std_actual": float(np.std(st_act)),
            "mae": st_mae,
            "rmse": st_rmse,
            "r2": st_r2
        })

    r2_within = float(1.0 - (ss_res_within / ss_tot_within)) if ss_tot_within > 0 else 0.0

    # Between-Station R^2
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

    # Delta-scale metrics
    y_delta_true = np.array([s["target_delta"] for s in test_samples])
    delta_mae = calc_mae(y_delta_true, preds_delta)
    delta_rmse = calc_rmse(y_delta_true, preds_delta)
    delta_r2 = calc_r2(y_delta_true, preds_delta)

    return {
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
        "persistence_mae": p_mae,
        "persistence_rmse": p_rmse,
        "persistence_r2": p_r2,
        "delta_mae": delta_mae,
        "delta_rmse": delta_rmse,
        "delta_r2": delta_r2,
        "station_metrics": pd.DataFrame(station_metrics).sort_values(by="r2"),
        "total_test_samples": len(test_samples)
    }


def print_lstm_report(train_samples: List[Dict], test_samples: List[Dict],
                      split_cutoff: pd.Timestamp, results: Dict[str, Any]):
    """Print comprehensive comparative evaluation report."""
    print("\n" + "=" * 110)
    print("      HAWAGUIDE 6-HOUR AHEAD PM2.5 RECURRENT FORECASTING REPORT (PyTorch 1-Layer LSTM + Met Sequences)")
    print("=" * 110)
    print(f"Lookback Window:     L = {SEQUENCE_LENGTH} hours (t-{SEQUENCE_LENGTH-1} to t) sliding multi-variate sequence")
    print(f"Sequence Features:   {', '.join(FEATURE_COLS)}")
    print(f"Target Formulation:  target_delta_6h = PM2.5(t+6) - rolling_mean_24h(t)  [back-transformed at test time]")
    print(f"Chronological Split: Training (First 75 Days) | Testing (Last 15 Days)")
    print(f"Split Date Boundary: {str(split_cutoff)[:19]} UTC")
    print(f"Training Samples:    {len(train_samples):,} sequences")
    print(f"Testing Samples:     {len(test_samples):,} sequences\n")

    # 1. Comparison vs Baseline
    print("-" * 110)
    print("               MODEL PERFORMANCE VS NAIVE PERSISTENCE BASELINE  [original PM2.5 ug/m3 scale]")
    print("-" * 110)
    print(f"{'Model / Estimator':<42} {'Test MAE':>12} {'Test RMSE':>12} {'Rel. Error':>12} {'Pooled R^2':>12}")
    print("-" * 110)
    print(
        f"{f'PyTorch LSTM ({SEQUENCE_LENGTH}h seq, 1-layer)':<42} "
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
    mae_imp = ((results['persistence_mae'] - results['mae']) / results['persistence_mae']) * 100.0
    rmse_imp = ((results['persistence_rmse'] - results['rmse']) / results['persistence_rmse']) * 100.0
    print(f"LSTM Improvement over Persistence Baseline:  {mae_imp:+.1f}% MAE  |  {rmse_imp:+.1f}% RMSE\n")

    # 2. Panel Variance & R^2 Decomposition
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
    print(f"{'1. Pooled R^2 (back-transformed to original scale):':<55} {results['r2_pooled']:>+10.4f}   Combined spatial + temporal performance")
    print(f"{'2. Between-Station R^2 (spatial cross-section):':<55} {results['r2_between']:>+10.4f}   Spatial baseline differentiation")
    print(f"{'3. Within-Station R^2 (station-mean centered):':<55} {results['r2_within']:>+10.4f}   Pure temporal within-station dynamics")
    print("-" * 110)
    print("Historical Model Benchmark Comparison:")
    print("  - XGBoost v1 (Raw Target, Lags only):           Within-Station R^2 = -0.108  | Pooled R^2 = +0.313")
    print("  - XGBoost v2 (Change Target, Lags + Trend):      Within-Station R^2 = -0.133  | Pooled R^2 = +0.298")
    print("  - XGBoost v3 (Change Target + Weather at t):    Within-Station R^2 = -0.108  | Pooled R^2 = +0.313")
    print(f"  - PyTorch LSTM ({SEQUENCE_LENGTH}h seq, 1-layer):       Within-Station R^2 = {results['r2_within']:>+6.3f}  | Pooled R^2 = {results['r2_pooled']:>+6.3f}")
    print("=" * 110 + "\n")

    # 3. Per-Station Evaluation Breakdown
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
    print("     HAWAGUIDE PM2.5 6-HOUR FORECASTER TRAINING & EVALUATION  (PyTorch LSTM Engine)")
    print("=" * 90)

    conn = get_db_connection()
    try:
        print("[1/4] Loading PM2.5 readings & weather observations...", flush=True)
        train_samples, test_samples, split_cutoff, scaler_X, scaler_y = prepare_datasets(conn)
        print(f"      [+] Dataset built: {len(train_samples):,} training sequences, {len(test_samples):,} test sequences.")
        print(f"      [+] Sequence Length: {SEQUENCE_LENGTH} hours | Horizon: {FORECAST_HORIZON} hours ahead.")

        print("\n[2/4] Transforming and scaling sequence arrays...", flush=True)
        X_train_scaled, y_train_scaled = transform_data(train_samples, scaler_X, scaler_y)

        print("\n[3/4] Initializing and training 2-Layer LSTM Forecaster...", flush=True)
        model = train_lstm_model(X_train_scaled, y_train_scaled, epochs=35, batch_size=128, lr=0.003)
        print("      [+] LSTM Training complete.")

        print("\n[4/4] Evaluating 6-hour ahead forecasts on 15-day holdout test set...", flush=True)
        results = evaluate_lstm_forecast(model, test_samples, scaler_X, scaler_y)

        print_lstm_report(train_samples, test_samples, split_cutoff, results)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
