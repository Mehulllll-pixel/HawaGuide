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
    for p in DELHI_NCR_PARKS:
        p_clean = p["name"].strip().lower().replace("-", " ")
        if clean == p_clean:
            return p
    for p in DELHI_NCR_PARKS:
        p_clean = p["name"].strip().lower().replace("-", " ")
        if clean in p_clean or p_clean in clean:
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


# ─── Nominatim Geocoder ──────────────────────────────────────────────────────────────
def geocode_location(place_name: str) -> Optional[Dict[str, Any]]:
    """
    Resolves a free-text place name to (lat, lon) via the Nominatim OSM API.
    Returns {'lat': float, 'lon': float, 'display_name': str} or None on failure.

    Policy:
    - Appends ', Delhi NCR, India' as a soft hint to bias results toward the
      region, but the caller can rely on the LLM-extracted place name as-is.
    - Respects Nominatim's usage policy: single request, proper User-Agent,
      no high-frequency polling.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": f"{place_name}, Delhi NCR, India",
        "format": "json",
        "limit": 1,
        "addressdetails": 0,
    }
    headers = {
        "User-Agent": "HawaGuide/1.0 (air-quality advisory app; contact@hawaguide.dev)"
    }
    try:
        resp = _requests.get(url, params=params, headers=headers, timeout=5)
        resp.raise_for_status()
        results = resp.json()
        if results:
            r = results[0]
            return {
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "display_name": r.get("display_name", place_name),
            }
    except Exception as exc:
        logging.warning("Nominatim geocoding failed for %r: %s", place_name, exc)
    return None


# ─── Gemini Structured-Output Field Extractor ────────────────────────────────────────────
# JSON schema for Gemini response_schema (all fields nullable so the model
# can return null for anything not clearly stated).
_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "age_group": {
            "type": "string",
            "enum": ["adult", "child", "elderly"],
            "nullable": True,
            "description": "Age group of the person going outside. null if not clearly stated."
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
            "description": "Planned physical activity level. null if not stated."
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
    "if only 'I' is used with no age cue, do NOT assume adult — return null. "
    "(6) For planned_activity: walking / cycling / moderate exercise = 'moderate'; "
    "running / jogging / intense = 'vigorous'; sitting / strolling / resting = 'rest'; "
    "'go outside' alone does not imply any activity — return null."
)


def _extract_fields_via_gemini(text: str, api_key: str) -> Dict[str, Any]:
    """
    Uses Gemini with response_schema (structured output / JSON mode) to extract
    agent input fields from free-text.  Uses the google-genai SDK (v2+) with
    gemini-3.6-flash and GenerateContentConfig.response_schema for strict JSON.
    Returns a dict with only the non-null fields resolved to their final values
    (location is geocoded to lat/lon here).
    Raises on unrecoverable API errors so the caller can surface them.
    """
    import time
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key)

    # Build the full prompt: system instructions prepended to the user message
    full_prompt = (
        f"{_EXTRACTION_SYSTEM}\n\n"
        f"User message: \"{text}\"\n\n"
        "Extract the fields as instructed. Return ONLY valid JSON matching the schema. "
        "Use null for any field not clearly stated."
    )

    # Retry up to 3 times on 503 overload or 429 quota (transient API pressure)
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
                    temperature=0.0,   # deterministic slot-filling
                )
            )
            raw = response.text.strip()
            break  # success
        except Exception as exc:
            last_exc = exc
            err_str = str(exc)
            is_503 = ("503" in err_str or "UNAVAILABLE" in err_str or "overload" in err_str.lower())
            is_429 = ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str)
            if is_503 or is_429:
                # Fast fail if daily quota is exhausted (no point waiting 60s per attempt)
                if "GenerateRequestsPerDayPerProjectPerModel" in err_str:
                    sentry_sdk.capture_exception(exc)
                    raise
                # Try to honour the API's retryDelay hint (e.g. '3s')
                import re as _re
                m = _re.search(r"retry.*?(\d+(?:\.\d+)?)s", err_str, _re.IGNORECASE)
                wait = float(m.group(1)) if m else 2 ** (attempt + 1)
                wait = max(1.0, min(wait, 3.0))  # clamp to max 3s
                logging.warning(
                    "Gemini transient error (attempt %d/3); retrying in %.1fs: %s",
                    attempt + 1, wait, exc
                )
                time.sleep(wait)
                continue
            raise  # non-transient errors are not retried
    else:
        sentry_sdk.capture_exception(last_exc)
        raise last_exc  # all retries exhausted

    # Parse the JSON (Gemini guarantees schema compliance when response_schema is set)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as jde:
        # Strip markdown fences if present
        try:
            raw_clean = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = json.loads(raw_clean)
        except Exception as parse_err:
            sentry_sdk.capture_exception(parse_err)
            raise

    extracted: Dict[str, Any] = {}

    # ─ age_group ────────────────────────────────────────────────────────────
    age = parsed.get("age_group")
    if age in ("adult", "child", "elderly"):
        extracted["age_group"] = age

    # ─ conditions ────────────────────────────────────────────────────────
    conds = parsed.get("conditions")
    if conds is not None:  # None = not mentioned; [] = explicitly healthy
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

    # ─ location (geocode via Nominatim) ────────────────────────────────────
    loc = parsed.get("location")
    if loc:
        geo = geocode_location(loc)
        if geo:
            extracted["lat"] = geo["lat"]
            extracted["lon"] = geo["lon"]
            extracted["_location_name"] = geo["display_name"].split(",")[0].strip()
            extracted["_location_display"] = geo["display_name"]
        else:
            # Gemini found a location name but geocoding failed — store the raw
            # name so the caller can surface a more helpful error if needed.
            extracted["_location_unresolved"] = loc

    return extracted


def _extract_fields_from_text(text: str) -> Dict[str, Any]:
    """
    Public interface used by /agent/ask.
    Calls Gemini structured-output extraction; falls back to degraded mode on error or missing API key
    so the session simply asks for the missing fields directly rather than crashing.
    """
    from dotenv import load_dotenv
    import os
    # Load .env relative to this file
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=_env_path)
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logging.warning("No Gemini API key found; field extraction in degraded mode.")
        return {"_extraction_degraded": True}
    try:
        return _extract_fields_via_gemini(text, api_key)
    except Exception as exc:
        logging.warning("Gemini field extraction failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return {"_extraction_degraded": True}


def _missing_fields(state: Dict[str, Any]) -> List[str]:
    """Return list of required field labels that are not yet present in the partial state."""
    missing = []
    if "lat" not in state or "lon" not in state:
        missing.append("location")
    if "age_group" not in state:
        missing.append("age group (adult / child / elderly)")
    if "conditions" not in state:
        missing.append("any health conditions (e.g. asthma, cardiac) or 'none'")
    if "smoker" not in state:
        missing.append("whether you smoke (yes / no)")
    if "planned_activity" not in state:
        missing.append("planned activity level (rest / moderate / vigorous)")
    if "duration_hours" not in state:
        missing.append("how long you plan to be outside (e.g. 1 hour, 1.5 hours)")
    return missing


def _build_clarification_question(missing: List[str], degraded: bool = False) -> str:
    """
    Build a clarifying question for the missing fields.
    When degraded=True, honestly surfaces that free-text understanding failed
    so the user knows the system didn't quietly misunderstand them.
    """
    if len(missing) == 1:
        field = missing[0]
        if degraded:
            return (
                "I'm having trouble understanding free-text right now, "
                f"so please share this detail directly: {field}."
            )
        return f"To give you a personalised recommendation, could you also share your {field}?"

    items = ", ".join(missing[:-1]) + f", and {missing[-1]}"
    if degraded:
        return (
            "I'm having trouble understanding free-text right now, so please share "
            f"each detail separately: {items}."
        )
    return (
        "To give you a personalised recommendation, I still need a few details: "
        f"{items}."
    )


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
    disclaimer: str


@app.post("/agent/ask", response_model=AgentAskResponse, tags=["Agent"])
def conversational_ask(req: AgentAskRequest):
    """
    Conversational Agent Endpoint with Session Memory:
    ---------------------------------------------------
    1. Retrieves (or creates) partial state for the given session_id.
    2. Extracts any newly-provided fields from the user's free-text message.
    3. Merges newly-extracted fields into the stored partial state.
    4. If required fields are still missing, returns a targeted clarifying question.
    5. Once all required fields are present, runs the full LangGraph agent workflow
       and returns the recommendation — without re-asking for fields already known.
    """
    session_id = req.session_id
    user_text = req.message
    disclaimer = "This tool provides general environmental air quality guidance, not medical advice; consult a healthcare provider for personal health decisions."

    # Step 1: Load (or initialise) session partial state
    session_state = _SESSIONS.get(session_id, {})

    # Step 2: Extract fields from the new message
    newly_extracted = _extract_fields_from_text(user_text)

    # Pull out the degradation flag BEFORE merging into session state —
    # it is per-turn metadata, not part of the user's profile.
    extraction_degraded = bool(newly_extracted.pop("_extraction_degraded", False))

    # Step 3: Merge — newly-extracted fields OVERWRITE stale values
    for key, val in newly_extracted.items():
        session_state[key] = val

    # Preserve alpha if provided in this request
    if req.alpha != 0.5 or "alpha" not in session_state:
        session_state["alpha"] = req.alpha

    # Step 4: Persist updated state
    _SESSIONS[session_id] = session_state

    # Step 5: Check for missing required fields
    missing = _missing_fields(session_state)
    if missing:
        question = _build_clarification_question(missing, degraded=extraction_degraded)
        return AgentAskResponse(
            session_id=session_id,
            status="clarifying",
            message=question,
            missing_fields=missing,
            extraction_degraded=extraction_degraded,
            recommendation=None,
            disclaimer=disclaimer
        )

    # Step 6: All fields present — run the full agent workflow
    try:
        result = run_agent_recommendation(
            lat=float(session_state["lat"]),
            lon=float(session_state["lon"]),
            age_group=session_state.get("age_group", "adult"),
            conditions=session_state.get("conditions", []),
            smoker=bool(session_state.get("smoker", False)),
            planned_activity=session_state.get("planned_activity", "moderate"),
            duration_hours=float(session_state.get("duration_hours", 1.0)),
            alpha=float(session_state.get("alpha", 0.5))
        )
        # Clear session after a successful recommendation so a fresh conversation
        # can begin naturally if the user sends another message with the same session_id.
        # To retain context for follow-ups, comment out the next line.
        _SESSIONS.pop(session_id, None)

        return AgentAskResponse(
            session_id=session_id,
            status="complete",
            message=result["recommendation"],
            missing_fields=[],
            recommendation=result,
            disclaimer=disclaimer
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent workflow failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
