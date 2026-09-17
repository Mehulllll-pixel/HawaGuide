"""
===================================================================================================
Test: Real Multi-Horizon Forecast Engine (100% XGBoost v3)
===================================================================================================

Target Verification:
--------------------
1. Verify `ForecastEngine.get_instance()` loads genuine trained model artifacts from disk.
2. Confirm 6 direct XGBoost regressors exist for horizons h=1..6.
3. Test end-to-end park prediction with live DB connection:
   - Valid dictionary keys (`current_pm25`, `baseline_24h`, `station_used`, `model_blend`, `hourly_trajectory`).
   - `model_blend` accurately identifies 100% XGBoost v3 with LSTM evaluated & excluded.
   - All 6 hourly trajectory points have positive, non-zero PM2.5 values.
   - Production forecast output equals the pure XGBoost prediction (`xgb_pm25 == forecast_pm25`).
===================================================================================================
"""

import sys
import unittest
import psycopg2
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ml.forecast_engine import ForecastEngine
from backend.ml.train_and_save_forecaster import get_db_connection


class TestForecastEngine(unittest.TestCase):

    def setUp(self):
        self.engine = ForecastEngine.get_instance()

    def test_forecast_engine_artifacts_loaded(self):
        """Confirm forecast engine loaded all 6 XGBoost horizon models."""
        self.assertTrue(self.engine.is_loaded, "ForecastEngine must load trained artifacts successfully")
        self.assertIsNotNone(self.engine.xgb_models)
        self.assertEqual(len(self.engine.xgb_models), 6, "Must have 6 XGBoost direct horizon regressors")
        for h in range(1, 7):
            self.assertIn(h, self.engine.xgb_models, f"Model for horizon {h} must be present")

    def test_predict_for_park_structure_and_values(self):
        """Confirm predict_for_park returns pure 100% XGBoost v3 multi-horizon trajectory."""
        try:
            conn = get_db_connection()
        except Exception as e:
            self.skipTest(f"Database connection unavailable: {e}")

        try:
            result = self.engine.predict_for_park(
                conn=conn,
                park_name="Lodhi Garden",
                park_lat=28.5931,
                park_lon=77.2197
            )

            # Top-level keys
            self.assertIn("current_pm25", result)
            self.assertIn("baseline_24h", result)
            self.assertIn("station_used", result)
            self.assertIn("model_blend", result)
            self.assertIn("hourly_trajectory", result)

            # Model blend accuracy
            self.assertEqual(
                result["model_blend"],
                "100% XGBoost v3 (LSTM evaluated and excluded after validation showed no meaningful contribution)"
            )

            # Hourly trajectory
            trajectory = result["hourly_trajectory"]
            self.assertEqual(len(trajectory), 6, "Trajectory must contain exactly 6 hourly predictions")

            valid_trends = {
                "Improving (Decreasing PM2.5)",
                "Worsening (Increasing PM2.5)",
                "Stable"
            }

            for idx, pt in enumerate(trajectory):
                h = idx + 1
                self.assertEqual(pt["hour_ahead"], h)
                self.assertGreater(pt["forecast_pm25"], 0.0, "Forecast PM2.5 must be positive")
                self.assertIn(pt["trend"], valid_trends, f"Unexpected trend label: {pt['trend']}")
                # 100% XGBoost output
                self.assertEqual(
                    pt["forecast_pm25"], pt["xgb_pm25"],
                    "In 100% XGBoost mode, forecast_pm25 must match xgb_pm25 exactly"
                )

        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
