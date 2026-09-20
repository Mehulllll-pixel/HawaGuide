"""
===================================================================================================
HawaGuide — Backend FastAPI Application & Spatial Optimization Service
===================================================================================================
"""

import os
import sys
import json
import math
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables from .env
for candidate in [PROJECT_ROOT / "backend" / ".env", PROJECT_ROOT / ".env", Path(".env")]:
    if candidate.is_file():
        load_dotenv(dotenv_path=candidate)
        break
else:
    load_dotenv()

import sentry_sdk

# ─── Sentry Error Tracking Initialization ─────────────────────────────────────
# Automatically instruments FastAPI to capture unhandled exceptions across all endpoints.
# Only initializes if SENTRY_DSN is provided in the environment.
SENTRY_DSN = os.getenv("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.2,
        send_default_pii=False,
    )
    logging.info("Sentry error tracking successfully initialized for FastAPI backend (sample_rate=0.2).")

import requests as _requests
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from backend.ml.optimizer import (
    optimize_parks,
    calculate_personalized_pevi,
    get_age_multiplier,
    get_condition_multiplier,
    get_personalized_risk_band,
    get_base_pevi_band,
    get_personalized_guidance,
    get_db_connection,
    MEDICAL_DISCLAIMER,
    DELHI_NCR_PARKS
)
from backend.ml.pevi import compute_pollutant_contributions
from backend.ml.forecast_engine import ForecastEngine

app = FastAPI(
    title="HawaGuide API",
    description="Hyperlocal Air Quality Intelligence & Personalized Exposure Vulnerability Index (PEVI) Service for Delhi NCR",
    version="1.0.0"
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Helper Functions ────────────────────────────────────────────────────────

def _find_park_by_name(location_name: str) -> Optional[Dict[str, Any]]:
    """
    Locates a park from the 40 known Delhi NCR parks via exact or fuzzy case-insensitive matching.
    """
    clean = location_name.strip().lower().replace("-", " ")
    if not clean or clean in ("no", "none", "neither", "yes", "true", "false", "rest", "walk", "moderate", "run", "in", "at", "to", "go", "is", "it", "safe", "outside"):
        return None
    for p in DELHI_NCR_PARKS:
        p_clean = p["name"].strip().lower().replace("-", " ")
        if clean == p_clean:
            return p
    # Check if a park name is mentioned in the user sentence (e.g. "Lodhi Garden" in sentence)
    for p in DELHI_NCR_PARKS:
        p_clean = p["name"].strip().lower().replace("-", " ")
        if len(p_clean) >= 4 and p_clean in clean:
            return p
    # Or if clean is a specific search query (>= 4 chars) contained within park name
    if len(clean) >= 4:
        for p in DELHI_NCR_PARKS:
            p_clean = p["name"].strip().lower().replace("-", " ")
            if clean in p_clean:
                return p
    return None


# ─── Pydantic Models for /optimize ───────────────────────────────────────────

class ParkRecommendation(BaseModel):
    rank: int = Field(..., description="Recommendation ranking (1 = optimal)")
    id: int = Field(..., description="Park identifier")
    name: str = Field(..., description="Official park / green space name")
    zone: Optional[str] = Field(None, description="Administrative / geographic zone")
    lat: float = Field(..., description="Latitude")
    lon: float = Field(..., description="Longitude")
    distance_km: float = Field(..., description="Geodetic distance in kilometers (via PostGIS ST_Distance)")
    distance_meters: float = Field(..., description="Geodetic distance in meters")
    base_pevi: float = Field(..., description="Current Base PEVI score from spatial interpolation")
    personalized_pevi: float = Field(..., description="Personalized PEVI score incorporating demographic & health risks")
    personalized_risk_band: str = Field(..., description="Relative risk band tailored for personalized PEVI scale")
    advisory_guidance: str = Field(..., description="Consumer-friendly outdoor air quality advisory guidance")
    norm_risk: float = Field(..., description="Min-max normalized environmental risk [0, 1]")
    norm_distance: float = Field(..., description="Min-max normalized geographic distance [0, 1]")
    score: float = Field(..., description="Composite multi-objective trade-off score (lower is better)")


class OptimizationResponse(BaseModel):
    status: str
    disclaimer: str = Field(..., description="Health and environmental advisory disclaimer")
    query: Dict[str, Any]
    total_parks: int
    recommendations: List[ParkRecommendation]


# ─── Pydantic Models for /locations ──────────────────────────────────────────

class PollutantBreakdown(BaseModel):
    pm25: float = Field(..., description="PM2.5 concentration in ug/m3")
    pm10: float = Field(..., description="PM10 concentration in ug/m3")
    no2: float = Field(..., description="NO2 concentration in ug/m3")
    so2: float = Field(..., description="SO2 concentration in ug/m3")
    o3: float = Field(..., description="O3 concentration in ug/m3")
    co: float = Field(..., description="CO concentration in mg/m3")


class LocationItem(BaseModel):
    id: Optional[int] = Field(None, description="Park identifier")
    name: str = Field(..., description="Official park / green space name")
    zone: Optional[str] = Field(None, description="Administrative / geographic zone")
    lat: float = Field(..., description="Latitude coordinate")
    lon: float = Field(..., description="Longitude coordinate")
    data_available: bool = Field(default=True, description="Whether current spatial interpolation and PEVI data is available for this location")
    current_pevi: Optional[float] = Field(None, description="Current Base PEVI score from spatial interpolation (None if data unavailable)")
    personalized_risk_band: Optional[str] = Field(None, description="Base risk band corresponding to current PEVI (None if data unavailable)")
    advisory_guidance: str = Field(..., description="Consumer-friendly outdoor air quality advisory guidance")
    pollutants: Optional[PollutantBreakdown] = Field(None, description="Current concentrations for all 6 criteria pollutants (None if data unavailable)")
    last_updated: Optional[str] = Field(None, description="Timestamp of latest interpolation / PEVI score")


class LocationsResponse(BaseModel):
    status: str = Field(default="success", description="Status string")
    disclaimer: str = Field(..., description="Health and environmental advisory disclaimer")
    total_locations: int = Field(..., description="Total count of green space locations returned")
    locations: List[LocationItem] = Field(..., description="List of all 40 green space locations with air quality metrics")


# ─── Pydantic Models for /forecast/{location_name} ──────────────────────────

class HourlyForecastPoint(BaseModel):
    hour_ahead: int = Field(..., ge=1, le=6, description="Forecast horizon in hours (1 to 6)")
    forecast_pm25: float = Field(..., description="Predicted PM2.5 concentration in ug/m3")
    delta_from_now: float = Field(..., description="Change in PM2.5 relative to current baseline in ug/m3")
    trend: str = Field(..., description="Forecast trend interpretation (Improving, Stable, Worsening)")


class LocationForecastResponse(BaseModel):
    status: str = Field(default="success", description="Status string")
    disclaimer: str = Field(..., description="Health and environmental advisory disclaimer")
    location_name: str = Field(..., description="Park / green space name")
    zone: Optional[str] = Field(None, description="Administrative / geographic zone")
    lat: float = Field(..., description="Latitude coordinate")
    lon: float = Field(..., description="Longitude coordinate")
    current_pm25: float = Field(..., description="Current baseline PM2.5 concentration in ug/m3")
    model_blend: str = Field(default="75% XGBoost v3 + 25% PyTorch LSTM", description="Ensemble formulation")
    forecast_horizon_hours: int = Field(default=6, description="Total forecast horizon in hours")
    hourly_trajectory: List[HourlyForecastPoint] = Field(..., description="Hourly PM2.5 forecast trajectory for 1 to 6 hours ahead")


# ─── Pydantic Models for /history/{location_name} ───────────────────────────

class HistoricalTrendPoint(BaseModel):
    date: str = Field(..., description="Date (YYYY-MM-DD) of the historical record")
    pevi: float = Field(..., description="Daily estimated PEVI score")
    personalized_risk_band: str = Field(..., description="Base risk band corresponding to daily PEVI")
    advisory_guidance: str = Field(..., description="Air quality advisory guidance for this day")
    pm25: float = Field(..., description="Daily average PM2.5 concentration in ug/m3")
    pm10: Optional[float] = Field(None, description="Daily average PM10 concentration in ug/m3")
    no2: Optional[float] = Field(None, description="Daily average NO2 concentration in ug/m3")
    so2: Optional[float] = Field(None, description="Daily average SO2 concentration in ug/m3")
    o3: Optional[float] = Field(None, description="Daily average O3 concentration in ug/m3")
    co: Optional[float] = Field(None, description="Daily average CO concentration in mg/m3")


class HistorySummary(BaseModel):
    avg_pevi: float = Field(..., description="Average PEVI across the historical period")
    avg_pm25: float = Field(..., description="Average PM2.5 across the historical period (ug/m3)")
    min_pm25: float = Field(..., description="Minimum PM2.5 recorded during the historical period (ug/m3)")
    max_pm25: float = Field(..., description="Maximum PM2.5 recorded during the historical period (ug/m3)")
    trend_direction: str = Field(..., description="Overall trend direction (Improving, Worsening, Stable)")


class LocationHistoryResponse(BaseModel):
    status: str = Field(default="success", description="Status string")
    disclaimer: str = Field(..., description="Health and environmental advisory disclaimer")
    location_name: str = Field(..., description="Park / green space name")
    zone: Optional[str] = Field(None, description="Administrative / geographic zone")
    lat: float = Field(..., description="Latitude coordinate")
    lon: float = Field(..., description="Longitude coordinate")
    days_requested: int = Field(..., description="Number of historical days requested")
    total_data_points: int = Field(..., description="Number of historical points returned")
    summary: HistorySummary = Field(..., description="Statistical summary over the requested time window")
    history: List[HistoricalTrendPoint] = Field(..., description="Chronological daily historical trend points")


# ─── Health / Root Endpoint ──────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def root():
    return {
        "service": "HawaGuide API",
        "status": "online",
        "disclaimer": MEDICAL_DISCLAIMER,
        "endpoints": {
            "GET /locations": "All 40 parks with base PEVI and 6 criteria pollutant values for map and list views",
            "GET /forecast/{location_name}": "6-hour PM2.5 forecast trajectory using 100% XGBoost v3 direct multi-horizon models",
            "GET /history/{location_name}?days=7": "Historical PEVI and PM2.5 trend for a park over the last N days",
            "GET /optimize": "Personalized park location optimizer with multi-objective trade-off ranking",
            "POST /agent/ask": "Conversational spatial air quality advisory agent",
            "GET /docs": "Interactive Swagger UI documentation"
        }
    }


# ─── 1. GET /locations ───────────────────────────────────────────────────────

@app.get("/locations", response_model=LocationsResponse, tags=["Locations"])
def get_all_locations():
    """
    Returns all 40 Delhi NCR urban green spaces with:
    - Official name, administrative zone, and geographic coordinates
    - data_available boolean flag (True if current kriging/PEVI data exists)
    - Current Base PEVI score from ordinary kriging spatial interpolation (or null if unavailable)
    - Base risk band classification (Low, Moderate, High, Extreme) (or null if unavailable)
    - Consumer-friendly advisory guidance
    - Current concentrations across all 6 criteria pollutants (PM2.5, PM10, NO2, SO2, O3, CO) (or null if unavailable)

    Ideal for map overview, heatmaps, and full green space listing without fabricating placeholder data.
    """
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                WITH latest_pevi AS (
                    SELECT DISTINCT ON (location_name)
                        location_name,
                        pevi_value,
                        timestamp,
                        pm25_ugm3, pm10_ugm3, no2_ugm3, so2_ugm3, o3_ugm3, co_mgm3
                    FROM pevi_scores
                    ORDER BY location_name, timestamp DESC
                )
                SELECT 
                    p.id,
                    p.name,
                    p.lat,
                    p.lon,
                    p.zone,
                    lp.pevi_value,
                    lp.timestamp AS pevi_timestamp,
                    lp.pm25_ugm3 AS pm25,
                    lp.pm10_ugm3 AS pm10,
                    lp.no2_ugm3 AS no2,
                    lp.so2_ugm3 AS so2,
                    lp.o3_ugm3 AS o3,
                    lp.co_mgm3 AS co
                FROM parks p
                LEFT JOIN latest_pevi lp ON p.name = lp.location_name
                ORDER BY p.name;
            """)
            rows = cur.fetchall()

        # Build location items
        locations = []
        for r in rows:
            has_data = (r["pevi_value"] is not None and r["pevi_timestamp"] is not None)
            ts_str = str(r["pevi_timestamp"]) if r["pevi_timestamp"] else None

            if has_data:
                pevi_val = round(float(r["pevi_value"]), 2)
                # Use get_base_pevi_band() — NOT get_personalized_risk_band().
                # Base PEVI uses quartile thresholds (<=4.13/<=4.81/<=5.65/else),
                # which are completely different from the personalized scale (<=6.0/7.7/10.3).
                risk_band = get_base_pevi_band(pevi_val)
                guidance = get_personalized_guidance(pevi_val)
                pollutants = PollutantBreakdown(
                    pm25=round(float(r["pm25"]), 2) if r["pm25"] is not None else 0.0,
                    pm10=round(float(r["pm10"]), 2) if r["pm10"] is not None else 0.0,
                    no2=round(float(r["no2"]), 2) if r["no2"] is not None else 0.0,
                    so2=round(float(r["so2"]), 2) if r["so2"] is not None else 0.0,
                    o3=round(float(r["o3"]), 2) if r["o3"] is not None else 0.0,
                    co=round(float(r["co"]), 2) if r["co"] is not None else 0.0,
                )
            else:
                pevi_val = None
                risk_band = None
                guidance = "Air quality data is currently unavailable for this green space. Please check back after the next scheduled spatial interpolation run."
                pollutants = None

            locations.append(LocationItem(
                id=r["id"],
                name=r["name"],
                zone=r["zone"],
                lat=float(r["lat"]),
                lon=float(r["lon"]),
                data_available=has_data,
                current_pevi=pevi_val,
                personalized_risk_band=risk_band,
                advisory_guidance=guidance,
                pollutants=pollutants,
                last_updated=ts_str
            ))

        return LocationsResponse(
            status="success",
            disclaimer=MEDICAL_DISCLAIMER,
            total_locations=len(locations),
            locations=locations
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch locations: {str(e)}")
    finally:
        conn.close()


# ─── 2. GET /forecast/{location_name} ────────────────────────────────────────

@app.get("/forecast/{location_name}", response_model=LocationForecastResponse, tags=["Forecasting"])
def get_location_forecast(location_name: str):
    """
    Returns the 6-hour PM2.5 hourly forecast trajectory for a specific named park
    using 100% XGBoost v3 direct multi-horizon models.

    - Returns 404 if the requested location name does not match any of the 40 Delhi NCR parks.
    - Uses live monitoring data & weather observations to run true model inference.
    - Provides hour-by-hour projected PM2.5 (ug/m3), delta from baseline, and trend direction.
    """
    matched_park = _find_park_by_name(location_name)
    if not matched_park:
        raise HTTPException(
            status_code=404,
            detail=f"Location '{location_name}' not found. Please choose from one of the 40 Delhi NCR parks."
        )

    conn = get_db_connection()
    try:
        engine = ForecastEngine.get_instance()
        forecast_result = engine.predict_for_park(
            conn=conn,
            park_name=matched_park["name"],
            park_lat=matched_park["lat"],
            park_lon=matched_park["lon"]
        )

        hourly_trajectory = [
            HourlyForecastPoint(
                hour_ahead=pt["hour_ahead"],
                forecast_pm25=pt["forecast_pm25"],
                delta_from_now=pt["delta_from_now"],
                trend=pt["trend"]
            )
            for pt in forecast_result["hourly_trajectory"]
        ]

        return LocationForecastResponse(
            status="success",
            disclaimer=MEDICAL_DISCLAIMER,
            location_name=matched_park["name"],
            zone=matched_park.get("zone"),
            lat=matched_park["lat"],
            lon=matched_park["lon"],
            current_pm25=forecast_result["current_pm25"],
            model_blend=forecast_result["model_blend"],
            forecast_horizon_hours=6,
            hourly_trajectory=hourly_trajectory
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Forecasting failed: {str(e)}")
    finally:
        conn.close()


# ─── 3. GET /history/{location_name} ─────────────────────────────────────────

@app.get("/history/{location_name}", response_model=LocationHistoryResponse, tags=["History"])
def get_location_history(
    location_name: str,
    days: int = Query(7, ge=1, le=30, description="Number of historical days to retrieve (1 to 30, default 7)")
):
    """
    Returns historical daily PEVI and PM2.5 trends for a specific named park over the last N days.
    
    - Lookback window: 1 to 30 days (default: 7 days).
    - Returns 404 if the requested location name does not match any of the 40 Delhi NCR parks.
    - Daily records include estimated PEVI, risk band, advisory guidance, and full 6-pollutant breakdown.
    - Includes aggregate period summary (avg PEVI, avg/min/max PM2.5, overall trend direction).
    """
    matched_park = _find_park_by_name(location_name)
    if not matched_park:
        raise HTTPException(
            status_code=404,
            detail=f"Location '{location_name}' not found. Please choose from one of the 40 Delhi NCR parks."
        )

    days_clamped = max(1, min(30, int(days)))
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Query top 3 nearest monitoring stations to this park for spatial weighting
            cur.execute("""
                SELECT id, name, lat, lon,
                       ST_Distance(location, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) as dist
                FROM stations
                ORDER BY dist ASC LIMIT 3;
            """, (matched_park["lon"], matched_park["lat"]))
            stations = cur.fetchall()

            if not stations:
                raise HTTPException(status_code=500, detail="No monitoring stations found in database.")

            weights = [1.0 / max(float(s["dist"]), 50.0)**2 for s in stations]
            tot_w = sum(weights)
            st_weights = {s["id"]: w / tot_w for s, w in zip(stations, weights)}
            station_ids = [s["id"] for s in stations]

            # Query daily average readings for each pollutant across nearest stations
            cur.execute("""
                SELECT 
                    date_trunc('day', timestamp)::date as day,
                    station_id,
                    pollutant,
                    AVG(value) as val
                FROM readings
                WHERE station_id = ANY(%s) 
                  AND timestamp >= (SELECT MAX(timestamp) FROM readings) - (%s || ' days')::interval
                GROUP BY day, station_id, pollutant
                ORDER BY day ASC;
            """, (station_ids, str(days_clamped)))
            rows = cur.fetchall()

        # Spatial aggregation by day
        by_day: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            d_str = str(r["day"])
            st_id = r["station_id"]
            poll = r["pollutant"]
            val = float(r["val"])
            w = st_weights.get(st_id, 1.0)

            if d_str not in by_day:
                by_day[d_str] = {
                    "weights": {p: 0.0 for p in ["pm25", "pm10", "no2", "so2", "o3", "co"]},
                    "values": {p: 0.0 for p in ["pm25", "pm10", "no2", "so2", "o3", "co"]}
                }
            if poll in by_day[d_str]["values"]:
                by_day[d_str]["values"][poll] += val * w
                by_day[d_str]["weights"][poll] += w

        history_points: List[HistoricalTrendPoint] = []
        for d_str, data in sorted(by_day.items()):
            polls: Dict[str, float] = {}
            for p in ["pm25", "pm10", "no2", "so2", "o3", "co"]:
                tw = data["weights"][p]
                polls[p] = round(data["values"][p] / tw, 2) if tw > 0 else 0.0

            contribs = compute_pollutant_contributions(
                o3_ugm3=polls["o3"],
                no2_ugm3=polls["no2"],
                pm25_ugm3=polls["pm25"],
                pm10_ugm3=polls["pm10"],
                so2_ugm3=polls["so2"],
                co_mgm3=polls["co"]
            )
            pevi = round(contribs["pevi_total"], 2)
            risk_band = get_base_pevi_band(pevi)
            guidance = get_personalized_guidance(pevi)

            history_points.append(HistoricalTrendPoint(
                date=d_str,
                pevi=pevi,
                personalized_risk_band=risk_band,
                advisory_guidance=guidance,
                pm25=polls["pm25"],
                pm10=polls["pm10"],
                no2=polls["no2"],
                so2=polls["so2"],
                o3=polls["o3"],
                co=polls["co"]
            ))

        pevi_vals = [p.pevi for p in history_points]
        pm25_vals = [p.pm25 for p in history_points]

        if len(pm25_vals) >= 2:
            diff = pm25_vals[-1] - pm25_vals[0]
            if diff < -2.0:
                trend_dir = "Improving (Decreasing Air Pollution)"
            elif diff > 2.0:
                trend_dir = "Worsening (Increasing Air Pollution)"
            else:
                trend_dir = "Stable"
        else:
            trend_dir = "Stable"

        summary = HistorySummary(
            avg_pevi=round(float(sum(pevi_vals) / len(pevi_vals)), 2) if pevi_vals else 0.0,
            avg_pm25=round(float(sum(pm25_vals) / len(pm25_vals)), 2) if pm25_vals else 0.0,
            min_pm25=round(float(min(pm25_vals)), 2) if pm25_vals else 0.0,
            max_pm25=round(float(max(pm25_vals)), 2) if pm25_vals else 0.0,
            trend_direction=trend_dir
        )

        return LocationHistoryResponse(
            status="success",
            disclaimer=MEDICAL_DISCLAIMER,
            location_name=matched_park["name"],
            zone=matched_park.get("zone"),
            lat=matched_park["lat"],
            lon=matched_park["lon"],
            days_requested=days_clamped,
            total_data_points=len(history_points),
            summary=summary,
            history=history_points
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"History retrieval failed: {str(e)}")
    finally:
        conn.close()


# ─── Optimization Endpoint ───────────────────────────────────────────────────

@app.get("/optimize", response_model=OptimizationResponse, tags=["Optimization"])
def get_optimized_parks(
    lat: float = Query(..., description="User starting latitude (e.g. 28.6328 for Connaught Place)", ge=-90.0, le=90.0),
    lon: float = Query(..., description="User starting longitude (e.g. 77.2197 for Connaught Place)", ge=-180.0, le=180.0),
    age_group: str = Query("adult", description="Demographic age group: 'adult' (1.0x), 'child' (1.3x), 'elderly' (1.3x)"),
    condition: str = Query("healthy", description="Health condition: 'healthy' (1.0x), 'respiratory' (1.5x), 'cardiac' (1.5x)"),
    duration_hours: float = Query(1.0, ge=0.1, le=24.0, description="Planned outdoor duration in hours (e.g. 1.0, 2.0)"),
    alpha: float = Query(0.5, ge=0.0, le=1.0, description="Multi-objective weight: alpha * risk + (1-alpha) * distance (0.0 to 1.0)")
):
    """
    Personalized Location Optimizer for Urban Green Spaces:
    ------------------------------------------------------
    1. Computes Personalized PEVI:
         Personalized_PEVI = Base_PEVI × age_mult × cond_mult × (1 + 0.15 × duration_hours)
    2. Computes true geodetic distance from (lat, lon) to each park via PostGIS ST_Distance.
    3. Min-max normalizes risk and distance across all 40 candidate parks.
    4. Computes composite score: Score = α × norm_risk + (1 - α) × norm_distance (lower is better).
    5. Returns the 40 candidate parks ranked by composite Score ascending.
    """
    try:
        ranked_parks = optimize_parks(
            start_lat=lat,
            start_lon=lon,
            age_group=age_group,
            condition=condition,
            duration_hours=duration_hours,
            alpha=alpha
        )

        age_mult = get_age_multiplier(age_group)
        cond_mult = get_condition_multiplier(condition)
        dur_mult = 1.0 + (0.15 * duration_hours)

        return OptimizationResponse(
            status="success",
            disclaimer="This tool provides general environmental air quality guidance, not medical advice; consult a healthcare provider for personal health decisions.",
            query={
                "start_lat": lat,
                "start_lon": lon,
                "age_group": age_group,
                "age_multiplier": age_mult,
                "condition": condition,
                "condition_multiplier": cond_mult,
                "duration_hours": duration_hours,
                "duration_multiplier": round(dur_mult, 3),
                "alpha": alpha,
                "total_multiplier": round(age_mult * cond_mult * dur_mult, 4)
            },
            total_parks=len(ranked_parks),
            recommendations=ranked_parks
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Optimization failed: {str(e)}")


from backend.ml.agent_graph import run_agent_recommendation


# ─── Session Store (in-memory) ──────────────────────────────────────────────
# Maps session_id -> partial state dict with keys matching agent inputs.
# Required fields for a full recommendation run:
#   lat, lon, age_group, conditions, smoker, planned_activity, duration_hours
# Optional: alpha (defaults to 0.5)
_SESSIONS: Dict[str, Dict[str, Any]] = {}

_REQUIRED_FIELDS = ["lat", "lon", "age_group", "conditions",
                    "smoker", "planned_activity", "duration_hours"]

_FIELD_ORDER = [
    "age_group",
    "conditions",
    "smoker",
    "planned_activity",
    "duration_hours",
    "location"
]

_FIELD_QUESTIONS = {
    "age_group": "What's your age? (Under 18 = child, 18-64 = adult, 65+ = elderly)",
    "conditions": "Do you have any of these health conditions: asthma, cardiac, or none?",
    "smoker": "Do you smoke tobacco?",
    "planned_activity": "What activity level are you planning: rest, moderate, or vigorous?",
    "duration_hours": "How long do you plan to be outside?",
    "location": "Where are you located in Delhi NCR?"
}

_FIELD_REASKS = {
    "age_group": "I didn't quite catch that — please provide your age as a number (e.g. 34) or category (child, adult, elderly):",
    "conditions": "I didn't quite catch that — please let me know if you have asthma, cardiac condition, or none:",
    "smoker": "I didn't quite catch that — please answer yes or no: do you smoke tobacco?",
    "planned_activity": "I didn't quite catch that — please choose your activity level: rest, moderate, or vigorous:",
    "duration_hours": "I didn't quite catch that — please specify how long you'll be outside (e.g. 30 minutes, 1 hour):",
    "location": "I couldn't find that location in Delhi NCR. Please specify a nearby Delhi NCR neighborhood or park name:"
}

AGE_BRACKET_LABELS = {
    "child": "child (under 18)",
    "adult": "adult (18-64)",
    "elderly": "elderly (65+)",
}


def map_age_to_group(val: Any) -> Optional[str]:
    """Maps a numeric age or category string into 'child', 'adult', or 'elderly'."""
    if isinstance(val, (int, float)):
        if val < 18:
            return "child"
        elif 18 <= val <= 64:
            return "adult"
        else:
            return "elderly"
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("child", "kid", "kids", "toddler", "teen", "teenager", "baby", "young"):
            return "child"
        if v in ("adult", "grown-up", "grownup"):
            return "adult"
        if v in ("elderly", "senior", "seniors", "senior citizen", "old", "60+", "65+", "aged", "retiree"):
            return "elderly"
        import re
        m = re.search(r"\b(\d{1,3})\b", v)
        if m:
            num = int(m.group(1))
            if num < 18:
                return "child"
            elif 18 <= num <= 64:
                return "adult"
            else:
                return "elderly"
    return None


# ─── Delhi NCR Bounding Region ────────────────────────────────────────────────
# Geographic bounding box defining the operational footprint for HawaGuide (Delhi + NCR satellite cities)
DELHI_NCR_BOUNDS = {
    "lat_min": 28.0,
    "lat_max": 29.2,
    "lon_min": 76.5,
    "lon_max": 77.9,
}


def is_within_delhi_ncr(lat: float, lon: float) -> bool:
    """
    Checks whether given coordinates fall within the Delhi NCR bounding area.
    Latitudes: 28.0 to 29.2, Longitudes: 76.5 to 77.9.
    """
    return (
        DELHI_NCR_BOUNDS["lat_min"] <= lat <= DELHI_NCR_BOUNDS["lat_max"]
        and DELHI_NCR_BOUNDS["lon_min"] <= lon <= DELHI_NCR_BOUNDS["lon_max"]
    )


# ─── Nominatim Geocoder & Reverse Geocoder ──────────────────────────────────
def reverse_geocode(lat: float, lon: float) -> str:
    """
    Reverse-geocodes lat/lon to a human-readable place name using OpenStreetMap Nominatim.
    Returns e.g. 'Lodhi Colony, New Delhi' or 'Jaipur, Rajasthan' or formatted coordinates on failure.
    """
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "zoom": 14,
        "addressdetails": 1,
    }
    headers = {
        "User-Agent": "HawaGuide/1.0 (air-quality advisory app; contact@hawaguide.dev)"
    }
    try:
        resp = _requests.get(url, params=params, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            addr = data.get("address", {})
            local_part = (
                addr.get("suburb")
                or addr.get("neighbourhood")
                or addr.get("residential")
                or addr.get("quarter")
                or addr.get("city_district")
                or addr.get("road")
            )
            city_part = (
                addr.get("city")
                or addr.get("town")
                or addr.get("village")
                or addr.get("municipality")
                or addr.get("county")
            )
            state_part = addr.get("state")

            if local_part and city_part and local_part.lower() != city_part.lower():
                return f"{local_part}, {city_part}"
            if city_part and state_part and city_part.lower() != state_part.lower():
                return f"{city_part}, {state_part}"
            if local_part and state_part:
                return f"{local_part}, {state_part}"
            if city_part:
                return city_part
            if "display_name" in data:
                parts = [p.strip() for p in data["display_name"].split(",") if p.strip()]
                if len(parts) >= 2:
                    return f"{parts[0]}, {parts[1]}"
                if parts:
                    return parts[0]
    except Exception as exc:
        logging.warning("Nominatim reverse geocoding failed for (%s, %s): %s", lat, lon, exc)
    return f"{lat:.4f}, {lon:.4f}"


def geocode_location(place_name: str) -> Optional[Dict[str, Any]]:
    """
    Resolves a free-text place name to (lat, lon) via the Nominatim OSM API.
    Returns {'lat': float, 'lon': float, 'display_name': str} or None on failure.
    Searches general place names with India / Delhi NCR fallback heuristics.
    """
    clean_name = place_name.strip()
    if not clean_name:
        return None

    url = "https://nominatim.openstreetmap.org/search"
    headers = {
        "User-Agent": "HawaGuide/1.0 (air-quality advisory app; contact@hawaguide.dev)"
    }

    # Determine query priority
    lower = clean_name.lower()
    is_ncr_keyword = any(k in lower for k in ["delhi", "noida", "gurugram", "gurgaon", "faridabad", "ghaziabad"])
    
    if is_ncr_keyword:
        queries = [clean_name, f"{clean_name}, Delhi NCR, India"]
    else:
        queries = [clean_name, f"{clean_name}, India", f"{clean_name}, Delhi NCR, India"]

    for q in queries:
        params = {
            "q": q,
            "format": "json",
            "limit": 1,
            "addressdetails": 1,
        }
        try:
            resp = _requests.get(url, params=params, headers=headers, timeout=5)
            if resp.status_code == 200:
                results = resp.json()
                if results:
                    r = results[0]
                    addr = r.get("address", {})
                    local = addr.get("suburb") or addr.get("neighbourhood") or addr.get("residential") or addr.get("city_district")
                    city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("state_district")
                    state = addr.get("state")
                    if local and city and local.lower() != city.lower():
                        display = f"{local}, {city}"
                    elif city and state and city.lower() != state.lower():
                        display = f"{city}, {state}"
                    elif local and state:
                        display = f"{local}, {state}"
                    elif city:
                        display = city
                    else:
                        display = r.get("display_name", clean_name).split(",")[0].strip()

                    return {
                        "lat": float(r["lat"]),
                        "lon": float(r["lon"]),
                        "display_name": display,
                    }
        except Exception as exc:
            logging.warning("Nominatim geocoding failed for %r (%s): %s", place_name, q, exc)
    return None


# ─── Structured-Output Field Extractor (Groq primary / Gemini fallback) ─────────

_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "age_group": {
            "type": "string",
            "enum": ["adult", "child", "elderly"],
            "nullable": True,
            "description": "Age group of the person going outside: 'adult' (18-64), 'child' (under 18), 'elderly' (65+). null if not clearly stated."
        },
        "conditions": {
            "type": "array",
            "items": {"type": "string"},
            "nullable": True,
            "description": (
                "List of health conditions. Valid values: 'asthma', 'copd', 'cardiac', 'respiratory'. "
                "Use [] for explicitly healthy/no conditions. null if not mentioned at all."
            )
        },
        "smoker": {
            "type": "boolean",
            "nullable": True,
            "description": "True if the person smokes tobacco. null if not mentioned."
        },
        "planned_activity": {
            "type": "string",
            "enum": ["rest", "moderate", "vigorous"],
            "nullable": True,
            "description": "Planned physical activity level: 'rest' (sedentary, sitting, resting, not moving), 'moderate' (walking, strolling, cycling, light exercise), 'vigorous' (running, jogging, intense sports). null if not stated."
        },
        "duration_hours": {
            "type": "number",
            "nullable": True,
            "description": "Planned outdoor duration in hours (e.g. 1.5). null if not stated."
        },
        "location": {
            "type": "string",
            "nullable": True,
            "description": (
                "Place name exactly as mentioned (e.g. 'Connaught Place', 'Hauz Khas Village'). "
                "null if no location is mentioned."
            )
        }
    },
    "required": ["age_group", "conditions", "smoker", "planned_activity", "duration_hours", "location"]
}

_GROQ_EXTRACTION_SCHEMA = {
    "name": "field_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "age_group": {
                "type": ["string", "null"],
                "enum": ["adult", "child", "elderly", None],
                "description": "Age group of the person going outside: 'adult' (18-64), 'child' (under 18), 'elderly' (65+). null if not clearly stated."
            },
            "conditions": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": (
                    "List of health conditions. Valid values: 'asthma', 'copd', 'cardiac', 'respiratory'. "
                    "Use [] for explicitly healthy/no conditions. null if not mentioned at all."
                )
            },
            "smoker": {
                "type": ["boolean", "null"],
                "description": "True if the person smokes tobacco. null if not mentioned."
            },
            "planned_activity": {
                "type": ["string", "null"],
                "enum": ["rest", "moderate", "vigorous", None],
                "description": "Planned physical activity level: 'rest' (sedentary, sitting, resting, not moving), 'moderate' (walking, strolling, cycling, light exercise), 'vigorous' (running, jogging, intense sports). null if not stated."
            },
            "duration_hours": {
                "type": ["number", "null"],
                "description": "Planned outdoor duration in hours (e.g. 1.5). null if not stated."
            },
            "location": {
                "type": ["string", "null"],
                "description": (
                    "Place name exactly as mentioned (e.g. 'Connaught Place', 'Hauz Khas Village'). "
                    "null if no location is mentioned."
                )
            }
        },
        "required": ["age_group", "conditions", "smoker", "planned_activity", "duration_hours", "location"],
        "additionalProperties": False
    }
}

_EXTRACTION_SYSTEM = (
    "You are a slot-filling assistant for an air quality app. "
    "Extract structured fields from the user's message. "
    "CRITICAL RULES: "
    "(1) Only extract a value if it is directly stated OR clearly and unambiguously implied by the user's words. "
    "(2) Do NOT guess, infer, or assume beyond what is stated. "
    "(3) Return null for any field that is unclear, ambiguous, or not mentioned. "
    "(4) For conditions[], return null (not []) if health status is simply not mentioned; "
    "only return [] if the user explicitly says they are healthy / have no conditions. "
    "Normalize conditions to ONLY these exact string values: 'asthma', 'copd', 'cardiac', 'respiratory'. "
    "Mapping rules: "
    "  - breathing trouble / difficulty breathing / breathlessness / wheeze / inhaler / lung issues => 'respiratory'; "
    "  - asthma / asthmatic => 'asthma'; "
    "  - COPD / emphysema / chronic bronchitis => 'copd'; "
    "  - heart condition / cardiac / cardiovascular / angina / hypertension => 'cardiac'. "
    "Never return a free-text condition description; always map to one of the four valid values. "
    "(5) For age_group: 'getting on in years', 'elderly mother', 'senior', 'old', '60+' etc. => 'elderly'; "
    "'kid', 'child', 'daughter/son who is young' => 'child'; "
    "if a numeric age is given: under 18 => 'child'; 18-64 => 'adult'; 65+ => 'elderly'; "
    "if only 'I' is used with no age cue, do NOT assume adult — return null. "
    "(6) For planned_activity: "
    "  - rest = sedentary, sitting, resting, lying down, not moving; "
    "  - moderate = walking, strolling, light activity, cycling, moderate exercise; "
    "  - vigorous = running, jogging, intense sports, heavy workout; "
    "'go outside' alone does not imply any activity — return null."
)


def _process_raw_extracted_json(raw: str) -> Dict[str, Any]:
    """Parse raw JSON string from LLM extraction and map to canonical state dict."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raw_clean = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw_clean)

    extracted: Dict[str, Any] = {}

    # ─ age_group ────────────────────────────────────────────────────────────
    age = parsed.get("age_group")
    mapped_age = map_age_to_group(age)
    if mapped_age:
        extracted["age_group"] = mapped_age

    # ─ conditions ────────────────────────────────────────────────────────
    conds = parsed.get("conditions")
    if conds is not None:
        valid = {"asthma", "copd", "cardiac", "respiratory"}
        extracted["conditions"] = [c for c in conds if c in valid]

    # ─ smoker ──────────────────────────────────────────────────────────────
    smoker = parsed.get("smoker")
    if smoker is not None:
        extracted["smoker"] = bool(smoker)

    # ─ planned_activity ─────────────────────────────────────────────────────
    activity = parsed.get("planned_activity")
    if activity in ("rest", "moderate", "vigorous"):
        extracted["planned_activity"] = activity

    # ─ duration_hours ───────────────────────────────────────────────────────
    dur = parsed.get("duration_hours")
    if dur is not None:
        try:
            extracted["duration_hours"] = float(dur)
        except (ValueError, TypeError):
            pass

    # ─ location (geocode via Nominatim / park matcher) ───────────────────────
    loc = parsed.get("location")
    if loc:
        matched_park = _find_park_by_name(loc)
        if matched_park:
            extracted["lat"] = matched_park["lat"]
            extracted["lon"] = matched_park["lon"]
            extracted["_location_name"] = matched_park["name"]
            extracted["_location_display"] = matched_park["name"]
        else:
            geo = geocode_location(loc)
            if geo:
                extracted["lat"] = geo["lat"]
                extracted["lon"] = geo["lon"]
                extracted["_location_name"] = geo["display_name"].split(",")[0].strip()
                extracted["_location_display"] = geo["display_name"]
            else:
                extracted["_location_unresolved"] = loc

    return extracted


def _extract_fields_via_groq(text: str, api_key: str, model: Optional[str] = None) -> Dict[str, Any]:
    """
    Uses Groq chat completions API with structured output / json_schema to extract
    agent input fields from free-text using openai/gpt-oss-120b.
    """
    import time
    from groq import Groq

    client = Groq(api_key=api_key)
    target_model = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    messages = [
        {"role": "system", "content": _EXTRACTION_SYSTEM},
        {
            "role": "user",
            "content": (
                f'User message: "{text}"\n\n'
                "Extract the fields as instructed. Return ONLY valid JSON matching the schema. "
                "Use null for any field not clearly stated."
            )
        }
    ]

    last_exc = None
    raw = None
    for attempt in range(3):
        try:
            try:
                response = client.chat.completions.create(
                    model=target_model,
                    messages=messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": _GROQ_EXTRACTION_SCHEMA
                    },
                    temperature=0.0
                )
            except Exception as schema_err:
                logging.warning("Groq json_schema failed (%s), falling back to json_object format", schema_err)
                response = client.chat.completions.create(
                    model=target_model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.0
                )
            raw = response.choices[0].message.content.strip()
            break
        except Exception as exc:
            last_exc = exc
            err_str = str(exc)
            is_rate_limit = ("429" in err_str or "rate_limit" in err_str.lower())
            is_overload = ("503" in err_str or "overloaded" in err_str.lower() or "500" in err_str)
            if is_rate_limit or is_overload:
                time.sleep(1.0 * (attempt + 1))
                continue
            sentry_sdk.capture_exception(exc)
            raise exc
    else:
        sentry_sdk.capture_exception(last_exc)
        raise last_exc

    return _process_raw_extracted_json(raw)


def _extract_fields_via_gemini(text: str, api_key: str) -> Dict[str, Any]:
    """
    Uses Gemini with response_schema (structured output / JSON mode) to extract
    agent input fields from free-text (maintained for fallback / compatibility).
    """
    import time
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key)

    full_prompt = (
        f"{_EXTRACTION_SYSTEM}\n\n"
        f"User message: \"{text}\"\n\n"
        "Extract the fields as instructed. Return ONLY valid JSON matching the schema. "
        "Use null for any field not clearly stated."
    )

    last_exc = None
    raw = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=full_prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_EXTRACTION_SCHEMA,
                    temperature=0.0,
                )
            )
            raw = response.text.strip()
            break
        except Exception as exc:
            last_exc = exc
            err_str = str(exc)
            is_503 = ("503" in err_str or "UNAVAILABLE" in err_str or "overload" in err_str.lower())
            is_429 = ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str)
            if is_503 or is_429:
                if "GenerateRequestsPerDayPerProjectPerModel" in err_str:
                    sentry_sdk.capture_exception(exc)
                    raise
                import re as _re
                m = _re.search(r"retry.*?(\d+(?:\.\d+)?)s", err_str, _re.IGNORECASE)
                wait = float(m.group(1)) if m else 2 ** (attempt + 1)
                if is_429 and wait > 3.0:
                    sentry_sdk.capture_exception(exc)
                    raise
                wait = max(1.0, min(wait, 3.0))
                logging.warning(
                    "Gemini transient error (attempt %d/3); retrying in %.1fs: %s",
                    attempt + 1, wait, exc
                )
                time.sleep(wait)
                continue
            raise
    else:
        sentry_sdk.capture_exception(last_exc)
        raise last_exc

    return _process_raw_extracted_json(raw)


def _extract_fields_via_llm(text: str) -> Dict[str, Any]:
    """
    Provider-neutral LLM extraction: prioritizes Groq (GROQ_API_KEY),
    falling back to Gemini (GEMINI_API_KEY / GOOGLE_API_KEY).
    """
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=_env_path)

    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key and groq_key.strip() and not groq_key.startswith("your_"):
        try:
            return _extract_fields_via_groq(text, groq_key)
        except Exception as exc:
            logging.warning("Groq extraction failed, checking fallback: %s", exc)
            sentry_sdk.capture_exception(exc)
            gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if gemini_key and not gemini_key.startswith("your_"):
                return _extract_fields_via_gemini(text, gemini_key)
            raise

    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gemini_key and not gemini_key.startswith("your_"):
        return _extract_fields_via_gemini(text, gemini_key)

    raise ValueError("Neither GROQ_API_KEY nor GEMINI_API_KEY is configured.")



def _parse_direct_fields(text: str) -> Dict[str, Any]:
    """
    Deterministic rule-based extractor for direct short responses, numbers, button clicks, and common phrases.
    Runs prior to / alongside LLM extraction.
    """
    import re
    clean = text.strip()
    lower = clean.lower()
    extracted: Dict[str, Any] = {}

    # 1. Direct Age Parsing
    # Check standalone number, "I am X", "X-year-old", "X years old", "X yo"
    age_match = re.search(r"\b(\d{1,3})\s*(?:-|\s)?(?:years?\s*old|yo|yrs?|yr)\b", lower)
    if not age_match:
        age_match = re.search(r"^(?:i am\s+|i'm\s+|age\s+)?(\d{1,3})$", lower)
    if age_match:
        num = int(age_match.group(1))
        if 0 < num <= 120:
            extracted["age_group"] = map_age_to_group(num)
    else:
        # Check standalone or in-sentence category words
        if re.search(r"\b(child|kid|kids|toddler|teen|teenager)\b", lower):
            extracted["age_group"] = "child"
        elif re.search(r"\b(adult|grown-?up)\b", lower):
            extracted["age_group"] = "adult"
        elif re.search(r"\b(elderly|senior|seniors|senior\s*citizen|old|60\+|65\+|retiree)\b", lower):
            extracted["age_group"] = "elderly"

    # 2. Direct Conditions Parsing
    if re.search(r"\b(no\s+(?:health\s+|medical\s+)?(?:conditions|issues|problems)|healthy|nothing|no\s+conditions)\b", lower) or lower in ("none", "no", "neither", "nil", "na", "n/a", "clean", "none of these"):
        extracted["conditions"] = []
    else:
        cond_list = []
        if re.search(r"\b(asthma|asthmatic)\b", lower):
            cond_list.append("asthma")
        if re.search(r"\b(cardiac|heart|heart\s+condition|cardiovascular)\b", lower):
            cond_list.append("cardiac")
        if re.search(r"\b(copd|emphysema|bronchitis)\b", lower):
            cond_list.append("copd")
        if re.search(r"\b(respiratory|breathing\s+trouble|breathlessness|lung\s+issues)\b", lower):
            cond_list.append("respiratory")
        if cond_list:
            extracted["conditions"] = cond_list

    # 3. Direct Smoker Parsing
    if re.search(r"\b(non-?smoker|nonsmoker|non\s+smoker|never|don't\s+smoke|do\s+not\s+smoke|no\s+smoker|not\s+a\s+smoker)\b", lower) or lower in ("no", "false"):
        extracted["smoker"] = False
    elif re.search(r"\b(smoker|i\s+smoke)\b", lower) or lower in ("yes", "true", "smoke", "yeah", "yep", "i do"):
        extracted["smoker"] = True

    # 4. Direct Activity Level Parsing
    if re.search(r"\b(vigorous|run|running|jog|jogging|intense|intense\s+sports|workout|heavy\s+exercise|soccer|football)\b", lower):
        extracted["planned_activity"] = "vigorous"
    elif re.search(r"\b(moderate|walk|walking|stroll|strolling|brisk\s+walk|cycling|cycle|bike|biking|light\s+exercise|light\s+activity)\b", lower):
        extracted["planned_activity"] = "moderate"
    elif re.search(r"\b(rest|resting|sit|sitting|sedentary|not\s+moving|lying\s+down|relaxing)\b", lower):
        extracted["planned_activity"] = "rest"

    # 5. Direct Duration Parsing
    if re.search(r"\b(?:an|one|1)\s+hour\b", lower) or lower in ("1hr", "1 hr", "1h", "1.0 hour"):
        extracted["duration_hours"] = 1.0
    elif re.search(r"\b(?:half\s+an?\s+hour|half\s+hour|30\s+mins?|30\s+minutes?)\b", lower) or lower in ("30min", "30 min", "30m", "0.5 hour", "0.5h"):
        extracted["duration_hours"] = 0.5
    elif re.search(r"\b45\s+mins?(?:utes?)?\b", lower) or lower in ("45m", "0.75 hour"):
        extracted["duration_hours"] = 0.75
    elif re.search(r"\b15\s+mins?(?:utes?)?\b", lower) or lower in ("15m", "0.25 hour"):
        extracted["duration_hours"] = 0.25
    elif re.search(r"\b2\s+hours?\b", lower) or lower in ("2 hrs", "2 hr", "2h", "two hours", "2.0 hours"):
        extracted["duration_hours"] = 2.0
    elif re.search(r"\b1\.5\s+hours?\b", lower) or lower in ("1.5 hrs", "1.5h", "90 minutes", "90 mins"):
        extracted["duration_hours"] = 1.5
    else:
        dur_hr_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b", lower)
        if dur_hr_match:
            extracted["duration_hours"] = float(dur_hr_match.group(1))
        else:
            dur_min_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:minutes?|mins?|m)\b", lower)
            if dur_min_match:
                extracted["duration_hours"] = round(float(dur_min_match.group(1)) / 60.0, 3)

    # 6. Direct Location Check against coordinates or known parks
    coord_match = re.search(r"(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)", clean)
    if coord_match:
        try:
            clat = float(coord_match.group(1))
            clon = float(coord_match.group(2))
            extracted["lat"] = clat
            extracted["lon"] = clon
            name_part = re.sub(r"\s*\(?-?\d{1,2}\.\d+\s*,\s*-?\d{1,3}\.\d+\)?\s*", "", clean).strip()
            if not name_part or re.match(r"^-?\d{1,2}\.\d+,\s*-?\d{1,3}\.\d+$", name_part):
                name_part = reverse_geocode(clat, clon)
            extracted["_location_name"] = name_part
            extracted["_location_display"] = name_part
        except ValueError:
            pass
    else:
        park = _find_park_by_name(clean)
        if park:
            extracted["lat"] = park["lat"]
            extracted["lon"] = park["lon"]
            extracted["_location_name"] = park["name"]
            extracted["_location_display"] = park["name"]

    return extracted


def _extract_fields_from_text(text: str) -> Dict[str, Any]:
    """
    Public interface used by /agent/ask.
    Calls direct parsing and Gemini structured-output extraction.
    For short answers (e.g. single button clicks, numbers, park names), uses direct parsing immediately.
    Falls back to degraded mode on error or missing API key.
    """
    direct = _parse_direct_fields(text)
    words = text.strip().split()

    # If direct parser successfully resolved fields and it's a short reply (<= 4 words),
    # return direct results immediately to avoid consuming LLM quota and minimize latency.
    if direct and len(words) <= 4:
        return direct

    from dotenv import load_dotenv
    import os
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=_env_path)
    
    llm_extracted = {}
    is_degraded = False
    try:
        llm_extracted = _extract_fields_via_llm(text)
    except Exception as exc:
        logging.warning("LLM field extraction failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        is_degraded = True

    combined = {**llm_extracted, **direct}
    if is_degraded:
        combined["_extraction_degraded"] = True
    return combined


def _missing_fields(state: Dict[str, Any]) -> List[str]:
    """Return list of required canonical field keys in fixed sequential order that are missing."""
    missing = []
    if state.get("age_group") not in ("adult", "child", "elderly"):
        missing.append("age_group")
    if "conditions" not in state or not isinstance(state.get("conditions"), list):
        missing.append("conditions")
    if "smoker" not in state or not isinstance(state.get("smoker"), bool):
        missing.append("smoker")
    if state.get("planned_activity") not in ("rest", "moderate", "vigorous"):
        missing.append("planned_activity")
    if "duration_hours" not in state or not isinstance(state.get("duration_hours"), (int, float)) or state.get("duration_hours") <= 0:
        missing.append("duration_hours")
    if "lat" not in state or "lon" not in state:
        missing.append("location")
    return missing


def _build_clarification_question(missing: List[str], degraded: bool = False) -> str:
    """
    Build a single targeted clarifying question for the next missing field in order.
    """
    if not missing:
        return ""
    next_field = missing[0]
    base_q = _FIELD_QUESTIONS.get(next_field, f"Could you provide your {next_field}?")
    if degraded:
        return (
            f"I'm having trouble understanding free-text right now, "
            f"so please answer this detail directly: {base_q}"
        )
    return base_q


class AgentRecommendRequest(BaseModel):
    lat: float = Field(..., description="User starting latitude (e.g. 28.6328)", ge=-90.0, le=90.0)
    lon: float = Field(..., description="User starting longitude (e.g. 77.2197)", ge=-180.0, le=180.0)
    age_group: str = Field("adult", description="Demographic: 'adult', 'child', 'elderly'")
    conditions: List[str] = Field(default_factory=list, description="Conditions list e.g. ['asthma', 'cardiac']")
    smoker: bool = Field(False, description="Tobacco smoker status (True/False)")
    planned_activity: str = Field("moderate", description="Activity level: 'rest', 'moderate', 'vigorous'")
    duration_hours: float = Field(1.0, ge=0.1, le=24.0, description="Planned outdoor exposure in hours")
    alpha: float = Field(0.5, ge=0.0, le=1.0, description="Weight on risk vs distance (0.0 to 1.0)")


class AgentRecommendResponse(BaseModel):
    status: str
    recommendation: str
    best_park: Dict[str, Any]
    best_time_window: str
    start_location_personalized_pevi: float
    recommended_park_personalized_pevi: float
    recommended_park_risk_band: str
    multipliers: Dict[str, Any]
    trace: List[Dict[str, Any]]
    disclaimer: str


@app.post("/agent/recommend", response_model=AgentRecommendResponse, tags=["Agent"])
def get_agent_recommendation(req: AgentRecommendRequest):
    """
    LangGraph StateGraph Agent Recommendation (structured, all-fields required):
    -----------------------------------------------------------------------------
    Executes the 5-node graph:
      [fetch_current] -> [fetch_forecast] -> [personalize] -> [reason (Gemini)] -> [explain]
    Returns plain-language guidance, optimal time window, top park, complete state trace, and disclaimer.
    """
    try:
        result = run_agent_recommendation(
            lat=req.lat,
            lon=req.lon,
            age_group=req.age_group,
            conditions=req.conditions,
            smoker=req.smoker,
            planned_activity=req.planned_activity,
            duration_hours=req.duration_hours,
            alpha=req.alpha
        )
        return AgentRecommendResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent workflow failed: {str(e)}")


# ─── Conversational /agent/ask endpoint ──────────────────────────────────────

class AgentAskRequest(BaseModel):
    session_id: str = Field(
        ...,
        description=(
            "Client-generated UUID that identifies the conversation session. "
            "Reuse the same ID across turns to enable memory/context merging."
        )
    )
    message: str = Field(
        ...,
        description="Free-text message from the user (e.g. 'Is it safe to go outside?')."
    )
    alpha: float = Field(
        0.5, ge=0.0, le=1.0,
        description="Optional risk-vs-distance weight; preserved across the session."
    )
    profile: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional saved profile dictionary with age_group, conditions, smoker, planned_activity."
    )


class AgentAskResponse(BaseModel):
    session_id: str
    status: str = Field(
        ...,
        description="'clarifying' if more info needed, 'complete' if full recommendation returned."
    )
    message: str = Field(
        ...,
        description="Agent reply: either a clarifying question or the full recommendation."
    )
    missing_fields: List[str] = Field(
        default_factory=list,
        description="List of fields still needed before a recommendation can be generated."
    )
    extraction_degraded: bool = Field(
        False,
        description=(
            "True when the Gemini field-extraction call failed (quota, outage, etc.) "
            "and the session fell back to asking for fields explicitly. "
            "Clients should surface this to users rather than implying the system understood them."
        )
    )
    recommendation: Optional[Dict[str, Any]] = Field(
        None,
        description="Full recommendation payload (same shape as /agent/recommend), or null if still clarifying."
    )
    collected_profile: Optional[Dict[str, Any]] = Field(
        default=None,
        description="User profile fields collected in session (age_group, conditions, smoker, planned_activity)."
    )
    disclaimer: str


def _is_closing_or_acknowledgment(text: str) -> bool:
    """
    Detects polite closings, thank-yous, and casual acknowledgments that should NOT trigger
    or restart the sequential clarification flow.
    Matches phrases like 'thank you', 'thanks', 'ok', 'okay', 'got it', 'bye',
    'goodbye', 'cool', 'great', 'appreciate it', etc. (case-insensitive with punctuation).
    """
    import re
    clean = re.sub(r"[^\w\s]", " ", text.lower()).strip()
    clean = re.sub(r"\s+", " ", clean)

    tokens = clean.split()
    if not tokens or len(tokens) > 8:
        return False

    closing_patterns = [
        r"^(?:thank\s*you(?:\s+(?:very\s+much|so\s+much|a\s+lot|hawa))?|thanks(?:\s+(?:a\s+lot|so\s+much|hawa))?|thx|ty)$",
        r"^(?:ok|okay|k|kk|alright|all\s+right|got\s+it|understood|noted|sure|yep)$",
        r"^(?:bye|goodbye|bye\s+bye|cya|see\s+ya|see\s+you|take\s+care|have\s+a\s+(?:good|great|nice)\s+day)$",
        r"^(?:cool|great|awesome|perfect|sounds\s+good|wonderful|nice|superb|excellent)$",
        r"^(?:appreciate\s+it|much\s+appreciated|many\s+thanks)$",
        r"^(?:ok|okay|cool|great|awesome|perfect|got\s+it|sounds\s+good)\s*,?\s*(?:thanks|thank\s*you|appreciate\s+it|bye|take\s+care)$",
        r"^(?:thanks|thank\s*you)\s*,?\s*(?:bye|goodbye|take\s+care|have\s+a\s+(?:good|great|nice)\s+day)$",
    ]
    if any(re.match(pattern, clean) for pattern in closing_patterns):
        return True

    # Check if short message (<= 5 tokens) is entirely made of closing vocabulary
    allowed_closing_tokens = {
        "thank", "you", "thanks", "thx", "ty", "ok", "okay", "k", "alright", "got", "it",
        "bye", "goodbye", "cool", "great", "awesome", "perfect", "sounds", "good", "nice",
        "appreciate", "much", "appreciated", "take", "care", "hawa", "so", "very", "a", "lot",
        "day", "have"
    }
    if len(tokens) <= 5 and all(t in allowed_closing_tokens for t in tokens):
        primary_keywords = {"thank", "thanks", "thx", "ty", "ok", "okay", "bye", "goodbye", "cool", "great", "awesome", "perfect", "appreciate", "appreciated"}
        if any(t in primary_keywords for t in tokens):
            return True

    return False


@app.post("/agent/ask", response_model=AgentAskResponse, tags=["Agent"])
def conversational_ask(req: AgentAskRequest):
    """
    Conversational Agent Endpoint with Sequential Clarification Flow:
    -----------------------------------------------------------------
    1. Detects casual closing / acknowledgment messages and responds politely without restarting clarification.
    2. Retrieves (or creates) partial state for the given session_id.
    3. Extracts newly-provided fields from user free-text / direct answers.
    4. Merges newly-extracted fields into stored partial state.
    5. Evaluates whether previous sequential question received an unparseable invalid answer (re-asks if so).
    6. If required fields are still missing, asks ONE field at a time in fixed order:
       age_group -> conditions -> smoker -> planned_activity -> duration_hours -> location.
    7. Confirms mapped age bracket before asking the next question.
    8. Once all required fields are present, runs full LangGraph agent workflow.
    """
    session_id = req.session_id
    user_text = req.message
    disclaimer = "This tool provides general environmental air quality guidance, not medical advice; consult a healthcare provider for personal health decisions."

    # Immediate check for casual acknowledgments / closings BEFORE any extraction or clarification
    if _is_closing_or_acknowledgment(user_text):
        session_state = _SESSIONS.get(session_id, {})
        prof = {}
        source_prof = req.profile if req.profile and isinstance(req.profile, dict) else session_state
        if source_prof.get("age_group") in ("adult", "child", "elderly"):
            prof["age_group"] = source_prof["age_group"]
        if "conditions" in source_prof and isinstance(source_prof.get("conditions"), list):
            prof["conditions"] = source_prof["conditions"]
        if "smoker" in source_prof and isinstance(source_prof.get("smoker"), bool):
            prof["smoker"] = source_prof["smoker"]
        if source_prof.get("planned_activity") in ("rest", "moderate", "vigorous"):
            prof["planned_activity"] = source_prof["planned_activity"]

        return AgentAskResponse(
            session_id=session_id,
            status="complete",
            message="You're welcome! Feel free to ask again whenever you're heading out.",
            missing_fields=[],
            extraction_degraded=False,
            recommendation=None,
            collected_profile=prof if prof else None,
            disclaimer=disclaimer
        )

    # Step 1: Load (or initialise) session partial state
    session_state = _SESSIONS.get(session_id, {})
    
    # Pre-seed session state from optional client-provided saved profile
    if req.profile and isinstance(req.profile, dict):
        for k in ("age_group", "conditions", "smoker", "planned_activity"):
            if k in req.profile and req.profile[k] is not None and k not in session_state:
                session_state[k] = req.profile[k]

    last_asked_field = session_state.get("_last_asked_field")

    # Step 2: Extract fields from the new message
    newly_extracted = _extract_fields_from_text(user_text)

    # Pull out degradation flag
    extraction_degraded = bool(newly_extracted.pop("_extraction_degraded", False))

    # Contextual duration fallback: standalone number when duration was explicitly asked
    if last_asked_field == "duration_hours" and "duration_hours" not in newly_extracted:
        try:
            val = float(user_text.strip())
            if 0.1 <= val <= 24.0:
                newly_extracted["duration_hours"] = val
        except ValueError:
            pass

    # Contextual location fallback: coordinates / park / geocode place name if location was explicitly asked
    if last_asked_field == "location" and "lat" not in newly_extracted and "lon" not in newly_extracted:
        coord_match = re.search(r"(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)", user_text)
        if coord_match:
            try:
                clat = float(coord_match.group(1))
                clon = float(coord_match.group(2))
                newly_extracted["lat"] = clat
                newly_extracted["lon"] = clon
                name_part = re.sub(r"\s*\(?-?\d{1,2}\.\d+\s*,\s*-?\d{1,3}\.\d+\)?\s*", "", user_text).strip()
                if not name_part or re.match(r"^-?\d{1,2}\.\d+,\s*-?\d{1,3}\.\d+$", name_part):
                    name_part = reverse_geocode(clat, clon)
                newly_extracted["_location_name"] = name_part
                newly_extracted["_location_display"] = name_part
            except ValueError:
                pass
        else:
            # Check local park matcher first
            matched_park = _find_park_by_name(user_text.strip())
            if matched_park:
                newly_extracted["lat"] = matched_park["lat"]
                newly_extracted["lon"] = matched_park["lon"]
                newly_extracted["_location_name"] = matched_park["name"]
                newly_extracted["_location_display"] = matched_park["name"]
            else:
                geo = geocode_location(user_text.strip())
                if geo:
                    newly_extracted["lat"] = geo["lat"]
                    newly_extracted["lon"] = geo["lon"]
                    newly_extracted["_location_name"] = geo["display_name"]
                    newly_extracted["_location_display"] = geo["display_name"]

    # Track if age was newly provided in this turn
    age_newly_set = ("age_group" in newly_extracted and "age_group" not in session_state)

    # Step 3: Merge — newly-extracted fields OVERWRITE stale values
    for key, val in newly_extracted.items():
        session_state[key] = val

    # Preserve alpha if provided in this request
    if req.alpha != 0.5 or "alpha" not in session_state:
        session_state["alpha"] = req.alpha

    # Helper to build current collected profile dictionary
    def _get_collected_profile() -> Optional[Dict[str, Any]]:
        prof = {}
        if session_state.get("age_group") in ("adult", "child", "elderly"):
            prof["age_group"] = session_state["age_group"]
        if "conditions" in session_state and isinstance(session_state.get("conditions"), list):
            prof["conditions"] = session_state["conditions"]
        if "smoker" in session_state and isinstance(session_state.get("smoker"), bool):
            prof["smoker"] = session_state["smoker"]
        if session_state.get("planned_activity") in ("rest", "moderate", "vigorous"):
            prof["planned_activity"] = session_state["planned_activity"]
        return prof if prof else None

    # Step 4: Check if previous sequential question received an unparseable / invalid answer
    is_invalid_answer = False
    if last_asked_field and last_asked_field in _missing_fields(session_state):
        is_invalid_answer = True

    # Step 5: Check for missing required fields in fixed sequential order
    missing = _missing_fields(session_state)
    if missing:
        next_field = missing[0]
        session_state["_last_asked_field"] = next_field
        _SESSIONS[session_id] = session_state

        if is_invalid_answer:
            question_text = _FIELD_REASKS.get(next_field, _FIELD_QUESTIONS[next_field])
            if extraction_degraded:
                question_text = f"I'm having trouble understanding free-text right now. {question_text}"
        else:
            base_q = _FIELD_QUESTIONS.get(next_field, f"Could you share your {next_field}?")
            prefix = ""
            if extraction_degraded:
                prefix += "I'm having trouble understanding free-text right now, so please answer this detail directly: "
            if age_newly_set:
                age_grp = session_state.get("age_group", "adult")
                bracket_label = AGE_BRACKET_LABELS.get(age_grp, f"{age_grp} (18-64)")
                prefix += f"Got it, categorizing you as {bracket_label}. "
            
            question_text = f"{prefix}{base_q}".strip()

        return AgentAskResponse(
            session_id=session_id,
            status="clarifying",
            message=question_text,
            missing_fields=missing,
            extraction_degraded=extraction_degraded,
            recommendation=None,
            collected_profile=_get_collected_profile(),
            disclaimer=disclaimer
        )

    # Step 6: All fields present — check Delhi NCR boundary before running optimization
    user_lat = float(session_state["lat"])
    user_lon = float(session_state["lon"])
    collected_final_profile = _get_collected_profile()

    if not is_within_delhi_ncr(user_lat, user_lon):
        # Resolve clean detected place name
        detected_place = session_state.get("_location_name")
        if not detected_place or re.match(r"^-?\d{1,2}\.\d+,\s*-?\d{1,3}\.\d+$", str(detected_place).strip()):
            detected_place = reverse_geocode(user_lat, user_lon)
        if not detected_place or re.match(r"^-?\d{1,2}\.\d+,\s*-?\d{1,3}\.\d+$", str(detected_place).strip()):
            detected_place = f"{user_lat:.4f}, {user_lon:.4f}"

        out_of_bounds_msg = (
            f"I'm currently built specifically for Delhi NCR and don't have real air quality data for {detected_place} yet — "
            f"I'll be able to help when I expand to your city!"
        )

        # Clear session after completing response
        _SESSIONS.pop(session_id, None)

        return AgentAskResponse(
            session_id=session_id,
            status="complete",
            message=out_of_bounds_msg,
            missing_fields=[],
            extraction_degraded=False,
            recommendation=None,
            collected_profile=collected_final_profile,
            disclaimer=disclaimer
        )

    _SESSIONS[session_id] = session_state
    try:
        result = run_agent_recommendation(
            lat=user_lat,
            lon=user_lon,
            age_group=session_state.get("age_group", "adult"),
            conditions=session_state.get("conditions", []),
            smoker=bool(session_state.get("smoker", False)),
            planned_activity=session_state.get("planned_activity", "moderate"),
            duration_hours=float(session_state.get("duration_hours", 1.0)),
            alpha=float(session_state.get("alpha", 0.5))
        )
        # Clear session after successful recommendation
        _SESSIONS.pop(session_id, None)

        return AgentAskResponse(
            session_id=session_id,
            status="complete",
            message=result["recommendation"],
            missing_fields=[],
            recommendation=result,
            collected_profile=collected_final_profile,
            disclaimer=disclaimer
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent workflow failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
