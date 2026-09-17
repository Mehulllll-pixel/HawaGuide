"""
===================================================================================================
Test: Ordinary Kriging Spatial Variation & Non-Degeneracy
===================================================================================================

Target Geostatistical Capability:
---------------------------------
Verify that Ordinary Kriging spatial interpolation across Delhi NCR:
1. Produces non-trivial spatial variation (variance > 0 and std dev > 0 across diverse park coordinates).
2. Prevents degenerate collapse to flat global means via the robust variogram refit strategy.
3. Produces physically bounded estimates (positive values within realistic environmental bounds).
===================================================================================================
"""

import sys
import unittest
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ml.kriging import fit_ok_robust, DELHI_NCR_PARKS


class TestKrigingSpatialVariation(unittest.TestCase):

    def test_kriging_produces_spatial_variation_across_parks(self):
        """
        Synthesize realistic monitoring station observations with genuine spatial gradients
        (e.g., higher in East/Industrial, lower in Central Ridge / South forest).
        Confirm that Kriging interpolation across 40 parks produces non-trivial spatial standard deviation.
        """
        # 10 synthetic station locations across NCR
        station_lons = np.array([77.10, 77.20, 77.30, 77.15, 77.25, 77.35, 77.05, 77.22, 77.18, 77.28])
        station_lats = np.array([28.70, 28.60, 28.55, 28.50, 28.65, 28.62, 28.45, 28.58, 28.72, 28.48])
        # PM2.5 values with East/West spatial gradient
        station_pm25 = np.array([35.0, 22.0, 58.0, 18.0, 42.0, 65.0, 20.0, 25.0, 38.0, 48.0])

        ok = fit_ok_robust(station_lons, station_lats, station_pm25, variogram_model="spherical")

        park_lons = [p["lon"] for p in DELHI_NCR_PARKS]
        park_lats = [p["lat"] for p in DELHI_NCR_PARKS]

        z_pred, _ = ok.execute("points", park_lons, park_lats)
        estimates = np.array([max(0.0, float(v)) for v in z_pred])

        # 1. Non-zero spatial variance
        std_dev = float(np.std(estimates))
        self.assertGreater(std_dev, 2.0, f"Kriging output must show spatial variation (std={std_dev:.2f} ug/m3)")

        # 2. Values are positive and strictly within realistic bounds
        self.assertTrue(np.all(estimates > 0.0), "All interpolated PM2.5 values must be positive")
        self.assertTrue(np.all(estimates < 200.0), "All interpolated PM2.5 values must be within plausible range")

        # 3. Min estimate is strictly less than max estimate
        min_val = float(np.min(estimates))
        max_val = float(np.max(estimates))
        self.assertLess(min_val, max_val - 5.0, "Spread between cleanest and dirtiest park must reflect spatial signal")

    def test_kriging_runs_against_real_database_and_parks(self):
        """
        Verify Ordinary Kriging directly against the populated PostgreSQL database:
        1. Queries real 24h station means from `readings` & `stations` tables.
        2. Fits Ordinary Kriging on genuine monitoring network observations.
        3. Interpolates across all 40 real Delhi NCR green spaces.
        4. Asserts genuine spatial variation and realistic physical bounds.
        """
        from backend.ml.optimizer import get_db_connection
        from backend.ml.kriging import fetch_recent_station_means

        try:
            conn = get_db_connection()
        except Exception as e:
            self.skipTest(f"Real PostgreSQL DB not reachable: {e}")

        try:
            df_means = fetch_recent_station_means(conn, pollutant="pm25", hours=24)
            self.assertGreaterEqual(len(df_means), 6, "Must have at least 6 active reporting stations in database")

            lons = df_means["lon"].to_numpy(dtype=float)
            lats = df_means["lat"].to_numpy(dtype=float)
            vals = df_means["value"].to_numpy(dtype=float)

            ok = fit_ok_robust(lons, lats, vals, variogram_model="spherical")

            park_lons = [p["lon"] for p in DELHI_NCR_PARKS]
            park_lats = [p["lat"] for p in DELHI_NCR_PARKS]

            z_pred, _ = ok.execute("points", park_lons, park_lats)
            park_estimates = np.array([max(0.0, float(v)) for v in z_pred])

            self.assertEqual(len(park_estimates), 40, "Must interpolate all 40 Delhi NCR parks")
            self.assertTrue(np.all(park_estimates > 0.0), "All real park PM2.5 estimates must be positive")
            
            real_std = float(np.std(park_estimates))
            self.assertGreater(real_std, 0.5, f"Real database Kriging must show non-zero spatial variation across parks (std={real_std:.2f})")

        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
