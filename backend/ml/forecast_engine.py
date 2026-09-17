"""
===================================================================================================
HawaGuide — Real-Time Multi-Horizon PM2.5 Inference Engine (100% XGBoost v3)
===================================================================================================

This module provides real-time 1 to 6-hour ahead PM2.5 forecasting by:
1. Loading the persisted trained multi-horizon XGBoost v3 models (and PyTorch LSTM state for reference).
2. Querying live PostgreSQL tables ('readings', 'weather', 'stations') for genuine recent time-series.
3. Feature engineering autoregressive lags, 6h/24h rolling means, velocity trend, cyclical encodings,
   and concurrent meteorological variables (wind speed, wind dir, humidity, rain, temperature).
4. Running live inference through pure XGBoost v3 (validated as superior to legacy LSTM ensemble).
===================================================================================================
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import joblib
import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import torch
import torch.nn as nn
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"


class MultiHorizonLSTMForecaster(nn.Module):
    """
    1-Layer LSTM with projection head for multi-horizon (h=1..6) PM2.5 delta forecasting.
    Must match the architecture in train_and_save_forecaster.py.
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


class ForecastEngine:
    _instance: Optional["ForecastEngine"] = None

    def __init__(self):
        self.xgb_models: Optional[Dict[int, Any]] = None
        self.lstm_model: Optional[MultiHorizonLSTMForecaster] = None
        self.scaler_X: Optional[StandardScaler] = None
        self.metadata: Optional[Dict[str, Any]] = None
        self.is_loaded = False
        self._load_artifacts()

    @classmethod
    def get_instance(cls) -> "ForecastEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_artifacts(self):
        """Loads XGBoost regressors, PyTorch LSTM, scalers, and metadata from disk."""
        xgb_path = MODELS_DIR / "xgboost_forecast_v3.joblib"
        lstm_path = MODELS_DIR / "lstm_forecast_v3.pt"
        scalers_path = MODELS_DIR / "lstm_scalers.joblib"
        meta_path = MODELS_DIR / "model_metadata.json"

        if not (xgb_path.exists() and lstm_path.exists() and scalers_path.exists()):
            logger.warning("Forecast models not found on disk at %s. Real inference unavailable.", MODELS_DIR)
            self.is_loaded = False
            return

        try:
            # 1. XGBoost models
            self.xgb_models = joblib.load(xgb_path)

            # 2. PyTorch LSTM
            self.lstm_model = MultiHorizonLSTMForecaster(
                input_dim=10, hidden_dim=32, num_layers=1, output_dim=6, dropout=0.0
            )
            self.lstm_model.load_state_dict(torch.load(lstm_path, map_location=torch.device("cpu")))
            self.lstm_model.eval()

            # 3. Scalers
            scalers = joblib.load(scalers_path)
            self.scaler_X = scalers["scaler_X"]

            # 4. Metadata
            if meta_path.exists():
                with open(meta_path) as f:
                    self.metadata = json.load(f)

            self.is_loaded = True
            logger.info("ForecastEngine successfully loaded 100% XGBoost v3 models (and LSTM reference).")
        except Exception as e:
            logger.error("Failed to load forecast model artifacts: %s", e)
            self.is_loaded = False

    def predict_for_park(self, conn, park_name: str, park_lat: float, park_lon: float) -> Dict[str, Any]:
        """
        Runs genuine end-to-end multi-horizon PM2.5 forecasting for a park:
        1. Queries nearest station(s) and pulls recent 24-hour PM2.5 and meteorological time series.
        2. Engineers lag, rolling, trend, and cyclical features.
        3. Executes live XGBoost .predict() (and PyTorch LSTM forward pass for reference).
        4. Generates 100% XGBoost v3 forecast trajectory (w_xgb=1.00).
        """
        if not self.is_loaded or self.xgb_models is None or self.lstm_model is None:
            raise RuntimeError(
                "Forecasting models are not loaded. Ensure train_and_save_forecaster.py has been executed."
            )

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Find the closest station to the park coordinates
            cur.execute("""
                SELECT id, name, lat, lon,
                       ST_Distance(location, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) as dist_meters
                FROM stations
                ORDER BY dist_meters ASC
                LIMIT 1;
            """, (park_lon, park_lat))
            station = cur.fetchone()

            if not station:
                raise ValueError(f"No monitoring station found near park '{park_name}'.")

            st_id = station["id"]
            st_name = station["name"]
            st_dist_km = round(float(station["dist_meters"]) / 1000.0, 2)

            # Query the latest 36 hours of hourly PM2.5 readings for this station
            cur.execute("""
                SELECT timestamp, value as pm25
                FROM readings
                WHERE station_id = %s AND pollutant = 'pm25'
                ORDER BY timestamp DESC
                LIMIT 72;
            """, (st_id,))
            pm_rows = cur.fetchall()

            if not pm_rows or len(pm_rows) < 12:
                # Fallback to any recent station if specific station has sparse data
                cur.execute("""
                    SELECT timestamp, value as pm25
                    FROM readings
                    WHERE pollutant = 'pm25'
                    ORDER BY timestamp DESC
                    LIMIT 72;
                """)
                pm_rows = cur.fetchall()

            # Query the latest 36 hours of weather for this station
            cur.execute("""
                SELECT timestamp, wind_speed, wind_direction, humidity, precipitation, temperature
                FROM weather
                WHERE station_id = %s
                ORDER BY timestamp DESC
                LIMIT 72;
            """, (st_id,))
            w_rows = cur.fetchall()

            if not w_rows:
                # Fallback to general weather
                cur.execute("""
                    SELECT timestamp, wind_speed, wind_direction, humidity, precipitation, temperature
                    FROM weather
                    ORDER BY timestamp DESC
                    LIMIT 72;
                """)
                w_rows = cur.fetchall()

        # Build clean chronological hourly DataFrame
        df_p = pd.DataFrame(pm_rows)
        df_p["timestamp"] = pd.to_datetime(df_p["timestamp"])
        df_p["hour_ts"] = df_p["timestamp"].dt.floor("h")
        df_p = df_p.groupby("hour_ts", as_index=False)["pm25"].mean().set_index("hour_ts").sort_index()

        full_idx = pd.date_range(start=df_p.index.min(), end=df_p.index.max(), freq="h")
        df_grid = df_p.reindex(full_idx)
        df_grid.index.name = "timestamp"
        df_grid["pm25"] = df_grid["pm25"].interpolate(method="linear", limit=3).bfill().ffill()

        # Join weather
        if w_rows:
            df_w = pd.DataFrame(w_rows)
            df_w["timestamp"] = pd.to_datetime(df_w["timestamp"])
            df_w["hour_ts"] = df_w["timestamp"].dt.floor("h")
            df_w = df_w.groupby("hour_ts").first().reindex(full_idx)

            for col in ["wind_speed", "wind_direction", "humidity", "precipitation", "temperature"]:
                if col in df_w.columns:
                    if col == "precipitation":
                        df_grid[col] = df_w[col].fillna(0.0)
                    else:
                        df_grid[col] = df_w[col].interpolate(method="linear").bfill().ffill()
                else:
                    df_grid[col] = 0.0
        else:
            for col in ["wind_speed", "wind_direction", "humidity", "precipitation", "temperature"]:
                df_grid[col] = 0.0

        # Fill any remaining NaNs
        df_grid = df_grid.bfill().ffill()

        # Compute feature series
        pm_s = df_grid["pm25"]
        df_grid["lag_1"] = pm_s.shift(1).fillna(pm_s)
        df_grid["lag_2"] = pm_s.shift(2).fillna(pm_s)
        df_grid["lag_3"] = pm_s.shift(3).fillna(pm_s)
        df_grid["lag_6"] = pm_s.shift(6).fillna(pm_s)
        df_grid["lag_24"] = pm_s.shift(24).fillna(pm_s)
        df_grid["rolling_mean_6h"] = pm_s.rolling(window=6, min_periods=1).mean()
        df_grid["rolling_mean_24h"] = pm_s.rolling(window=24, min_periods=1).mean()
        df_grid["hour_of_day"] = df_grid.index.hour
        df_grid["day_of_week"] = df_grid.index.dayofweek
        df_grid["recent_trend"] = df_grid["lag_1"] - df_grid["lag_3"]

        # Current baseline anchor (time t)
        current_pm25 = float(df_grid["pm25"].iloc[-1])
        baseline_24h = float(df_grid["rolling_mean_24h"].iloc[-1])

        # ---------------------------------------------------------------------
        # 1. XGBoost Real Inference
        # ---------------------------------------------------------------------
        xgb_feature_cols = [
            "lag_1", "lag_2", "lag_3", "lag_6", "lag_24",
            "rolling_mean_6h", "rolling_mean_24h",
            "hour_of_day", "day_of_week", "recent_trend",
            "wind_speed", "wind_direction", "humidity", "precipitation", "temperature"
        ]
        xgb_feature_row = df_grid[xgb_feature_cols].iloc[[-1]]

        xgb_predictions = {}
        for h in range(1, 7):
            pred_delta = float(self.xgb_models[h].predict(xgb_feature_row)[0])
            xgb_predictions[h] = max(5.0, pred_delta + baseline_24h)

        # ---------------------------------------------------------------------
        # 2. PyTorch LSTM Real Inference
        # ---------------------------------------------------------------------
        rad_wd = np.radians(df_grid["wind_direction"].to_numpy())
        df_grid["wind_dir_sin"] = np.sin(rad_wd)
        df_grid["wind_dir_cos"] = np.cos(rad_wd)
        hours = df_grid.index.hour.to_numpy()
        df_grid["hour_sin"] = np.sin(2.0 * np.pi * hours / 24.0)
        df_grid["hour_cos"] = np.cos(2.0 * np.pi * hours / 24.0)
        df_grid["day_of_week_norm"] = df_grid.index.dayofweek.to_numpy() / 6.0

        lstm_feature_cols = [
            "pm25", "wind_speed", "wind_dir_sin", "wind_dir_cos",
            "humidity", "precipitation", "temperature",
            "hour_sin", "hour_cos", "day_of_week_norm"
        ]
        
        # Take the last 12 hours for the sequence window
        if len(df_grid) >= 12:
            seq_df = df_grid[lstm_feature_cols].iloc[-12:]
        else:
            # Pad if needed
            pad_rows = 12 - len(df_grid)
            first_row = df_grid[lstm_feature_cols].iloc[[0]]
            pad_df = pd.concat([first_row] * pad_rows, ignore_index=True)
            seq_df = pd.concat([pad_df, df_grid[lstm_feature_cols]], ignore_index=True)

        seq_raw = seq_df.to_numpy().astype(np.float32)  # (12, 10)
        F = seq_raw.shape[1]
        seq_scaled = self.scaler_X.transform(seq_raw.reshape(-1, F)).reshape(1, 12, F)

        with torch.no_grad():
            preds_delta_lstm = self.lstm_model(torch.tensor(seq_scaled, dtype=torch.float32)).numpy()[0]  # (6,)

        lstm_predictions = {}
        for idx, h in enumerate(range(1, 7)):
            lstm_predictions[h] = max(5.0, float(preds_delta_lstm[idx]) + baseline_24h)

        # ---------------------------------------------------------------------
        # 3. Production Forecast Trajectory (100% XGBoost v3, w_xgb=1.00)
        # ---------------------------------------------------------------------
        # LSTM forward pass was executed above and is retained for reference (w_lstm=0.0).
        # Empirical validation demonstrated XGBoost v3 alone delivers superior accuracy & skill.
        trajectory = []
        for h in range(1, 7):
            pred_final = round(xgb_predictions[h], 1)
            delta = round(pred_final - current_pm25, 1)

            if pred_final < current_pm25 - 2.0:
                trend = "Improving (Decreasing PM2.5)"
            elif pred_final > current_pm25 + 2.0:
                trend = "Worsening (Increasing PM2.5)"
            else:
                trend = "Stable"

            trajectory.append({
                "hour_ahead": h,
                "forecast_pm25": pred_final,
                "delta_from_now": delta,
                "trend": trend,
                "xgb_pm25": round(xgb_predictions[h], 1),
                "lstm_pm25_reference": round(lstm_predictions[h], 1)
            })

        return {
            "current_pm25": round(current_pm25, 1),
            "baseline_24h": round(baseline_24h, 1),
            "station_used": {
                "id": st_id,
                "name": st_name,
                "distance_km": st_dist_km
            },
            "model_blend": "100% XGBoost v3 (LSTM evaluated and excluded after validation showed no meaningful contribution)",
            "hourly_trajectory": trajectory
        }
