"""
===================================================================================================
HawaGuide — LangGraph Agent Workflow with Google Gemini Integration
===================================================================================================

Graph Architecture:
-------------------
  (START)
     │
     ▼
[fetch_current]   ──> Queries current PEVI & dominant pollutant contributions for location
     │
     ▼
[fetch_forecast]  ──> Fetches 6-hour PM2.5 trajectory from 75/25 XGBoost+LSTM ensemble
     │
     ▼
[personalize]     ──> Computes personalized risk (age, condition, smoker, activity, duration) & ranks 40 parks
     │
     ▼
[reason]          ──> Google Gemini reasoning: picks optimal 6h time window & best park
     │
     ▼
[explain]         ──> Generates 2-3 sentence consumer-friendly recommendation with reasoning
     │
     ▼
   (END)
===================================================================================================
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, TypedDict

from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ml.agent_tools import (
    get_current_pevi,
    get_forecast,
    compute_personalized_risk,
    get_park_options,
    MEDICAL_DISCLAIMER
)

# Load .env
for candidate in [PROJECT_ROOT / "backend" / ".env", PROJECT_ROOT / ".env", Path(".env")]:
    if candidate.is_file():
        load_dotenv(dotenv_path=candidate)
        break
else:
    load_dotenv()

# State Schema
class AgentState(TypedDict):
    # Inputs
    lat: float
    lon: float
    age_group: str
    conditions: List[str]
    smoker: bool
    planned_activity: str
    duration_hours: float
    alpha: float
    
    # Node outputs
    current_pevi_data: Dict[str, Any]
    forecast_data: List[Dict[str, Any]]
    personalized_risk_data: Dict[str, Any]
    candidate_parks: List[Dict[str, Any]]
    reasoning_analysis: Dict[str, Any]
    recommendation_text: str
    
    # Audit trail
    node_trace: List[Dict[str, Any]]


# ─── Node 1: fetch_current ───────────────────────────────────────────────────

def fetch_current_node(state: AgentState) -> Dict[str, Any]:
    current_data = get_current_pevi(lat=state["lat"], lon=state["lon"])
    trace_entry = {
        "node": "fetch_current",
        "description": "Retrieved current multi-pollutant vulnerability from spatial interpolation",
        "data": {
            "location_name": current_data.get("location_name"),
            "base_pevi": current_data.get("pevi_value"),
            "pollutants": current_data.get("pollutants"),
            "contributions": current_data.get("contributions")
        }
    }
    existing_trace = list(state.get("node_trace", []))
    existing_trace.append(trace_entry)
    return {
        "current_pevi_data": current_data,
        "node_trace": existing_trace
    }


# ─── Node 2: fetch_forecast ──────────────────────────────────────────────────

def fetch_forecast_node(state: AgentState) -> Dict[str, Any]:
    forecast_list = get_forecast(lat=state["lat"], lon=state["lon"], hours_ahead=6)
    trace_entry = {
        "node": "fetch_forecast",
        "description": "Generated 6-hour PM2.5 trajectory from 75/25 XGBoost+LSTM ensemble",
        "data": {
            "forecast_horizon_hours": len(forecast_list),
            "hourly_trajectory": forecast_list
        }
    }
    existing_trace = list(state.get("node_trace", []))
    existing_trace.append(trace_entry)
    return {
        "forecast_data": forecast_list,
        "node_trace": existing_trace
    }


# ─── Node 3: personalize ─────────────────────────────────────────────────────

def personalize_node(state: AgentState) -> Dict[str, Any]:
    base_pevi = state["current_pevi_data"].get("pevi_value", 4.8)
    pers_risk = compute_personalized_risk(
        base_pevi=base_pevi,
        age_group=state.get("age_group", "adult"),
        conditions=state.get("conditions", []),
        smoker=state.get("smoker", False),
        planned_activity=state.get("planned_activity", "moderate"),
        duration_hours=state.get("duration_hours", 1.0)
    )
    
    parks = get_park_options(
        lat=state["lat"],
        lon=state["lon"],
        age_group=state.get("age_group", "adult"),
        conditions=state.get("conditions", []),
        smoker=state.get("smoker", False),
        planned_activity=state.get("planned_activity", "moderate"),
        duration_hours=state.get("duration_hours", 1.0),
        alpha=state.get("alpha", 0.5),
        top_k=5
    )

    trace_entry = {
        "node": "personalize",
        "description": "Calculated 5-factor personalized inhalation multipliers and ran 40-park spatial optimizer",
        "data": {
            "start_location_personalized_pevi": pers_risk.get("personalized_pevi"),
            "start_location_risk_band": pers_risk.get("personalized_risk_band"),
            "multipliers": pers_risk.get("multipliers"),
            "top_candidate_parks": [
                {
                    "rank": p["rank"],
                    "name": p["name"],
                    "distance_km": p["distance_km"],
                    "base_pevi": p["base_pevi"],
                    "personalized_pevi": p["personalized_pevi"],
                    "personalized_risk_band": p["personalized_risk_band"],
                    "score": p["score"]
                }
                for p in parks
            ]
        }
    }
    existing_trace = list(state.get("node_trace", []))
    existing_trace.append(trace_entry)
    return {
        "personalized_risk_data": pers_risk,
        "candidate_parks": parks,
        "node_trace": existing_trace
    }


from backend.ml.optimizer import get_personalized_risk_band, get_personalized_guidance

def evaluate_recommendation_tier(
    candidate_parks: List[Dict[str, Any]],
    forecast_list: List[Dict[str, Any]],
    current_pm25: float,
    compound_multiplier: float
) -> Dict[str, Any]:
    """
    Evaluates explicit 3-Tier recommendation logic:
      - TIER 1: Best park is Low (Band 1) or Moderate (Band 2) right now -> Recommend now, no caveats.
      - TIER 2: Best park is High/Extreme now, BUT crosses into Low/Moderate (or improves band) in 6h -> Lead with wait instruction & confidence check.
      - TIER 3: Best park is High/Extreme now AND stays that way for all 6h -> Honest advice that waiting won't help enough.
    """
    band_ranks = {"Low (Band 1)": 1, "Moderate (Band 2)": 2, "High (Band 3)": 3, "Extreme (Band 4)": 4}
    band_thresholds = {1: 6.00, 2: 7.70, 3: 10.30}
    
    if not candidate_parks:
        candidate_parks = [{"name": "Lodhi Garden", "distance_km": 5.0, "base_pevi": 3.5, "personalized_pevi": 8.0, "personalized_risk_band": "High (Band 3)", "score": 0.2}]
    
    best_park = candidate_parks[0]
    best_park_cur_band = best_park.get("personalized_risk_band", "Moderate (Band 2)")
    best_park_cur_rank = band_ranks.get(best_park_cur_band, 2)
    best_park_cur_pevi = float(best_park.get("personalized_pevi", 8.0))
    best_park_base_pevi = float(best_park.get("base_pevi", 3.5))
    
    # ── TIER 1: Current best park is Low (Band 1) or Moderate (Band 2) ───────────
    if best_park_cur_rank <= 2:
        best_hour = 1
        best_pm25 = current_pm25
        if forecast_list:
            min_fc = min(forecast_list, key=lambda f: float(f.get("forecast_pm25_ugm3", current_pm25)))
            best_hour = min_fc.get("hour_ahead", 1)
            best_pm25 = float(min_fc.get("forecast_pm25_ugm3", current_pm25))
            
        return {
            "tier": "TIER_1",
            "tier_name": "Tier 1 (Go Now - Favorable)",
            "recommended_park": best_park.get("name"),
            "best_park_obj": best_park,
            "best_hour": best_hour,
            "best_pm25": best_pm25,
            "current_band": best_park_cur_band,
            "current_pevi": best_park_cur_pevi,
            "improving_park": None,
            "improved_hour": None,
            "improved_band": None,
            "improved_pevi": None,
            "is_near_boundary": False,
            "boundary_margin": None
        }

    # ── Analyze 6-Hour Forecast across Candidates for TIER 2 vs TIER 3 ──────────
    tier2_candidate = None
    
    for park in candidate_parks:
        p_name = park.get("name")
        p_base = float(park.get("base_pevi", 3.5))
        p_cur_pevi = float(park.get("personalized_pevi", p_base * compound_multiplier))
        p_cur_band = park.get("personalized_risk_band", get_personalized_risk_band(p_cur_pevi))
        p_cur_rank = band_ranks.get(p_cur_band, 4)
        
        for fc in forecast_list:
            fc_pm25 = float(fc.get("forecast_pm25_ugm3", current_pm25))
            delta_pm25 = fc_pm25 - current_pm25
            delta_base = 0.283 * (delta_pm25 / 60.0)
            proj_base = max(0.1, p_base + delta_base)
            proj_pers = round(proj_base * compound_multiplier, 4)
            proj_band = get_personalized_risk_band(proj_pers)
            proj_rank = band_ranks.get(proj_band, 4)
            
            # Tier 2 condition: crosses into Low/Moderate (proj_rank <= 2) or improves risk band
            if (proj_rank <= 2 and proj_rank < p_cur_rank) or (proj_rank < p_cur_rank):
                threshold = band_thresholds.get(proj_rank, 7.70)
                margin = abs(proj_pers - threshold)
                is_near_boundary = (margin <= 0.05 * threshold)
                
                if tier2_candidate is None or proj_rank < tier2_candidate["proj_rank"]:
                    tier2_candidate = {
                        "park_name": p_name,
                        "park_obj": park,
                        "hour": fc.get("hour_ahead", 1),
                        "fc_pm25": fc_pm25,
                        "current_band": p_cur_band,
                        "current_pevi": p_cur_pevi,
                        "projected_band": proj_band,
                        "projected_pevi": proj_pers,
                        "proj_rank": proj_rank,
                        "is_near_boundary": is_near_boundary,
                        "boundary_margin": round(margin, 4)
                    }
                    if proj_rank <= 2:
                        break

    if tier2_candidate:
        return {
            "tier": "TIER_2",
            "tier_name": "Tier 2 (Wait for Window - Crossing into Better Band)",
            "recommended_park": tier2_candidate["park_name"],
            "best_park_obj": tier2_candidate["park_obj"],
            "best_hour": tier2_candidate["hour"],
            "best_pm25": tier2_candidate["fc_pm25"],
            "current_band": best_park_cur_band,
            "current_pevi": best_park_cur_pevi,
            "improving_park": tier2_candidate["park_name"],
            "improved_hour": tier2_candidate["hour"],
            "improved_band": tier2_candidate["projected_band"],
            "improved_pevi": tier2_candidate["projected_pevi"],
            "is_near_boundary": tier2_candidate["is_near_boundary"],
            "boundary_margin": tier2_candidate["boundary_margin"]
        }

    # ── TIER 3: Stays High/Extreme throughout all 6 hours ──────────────────────
    min_fc = min(forecast_list, key=lambda f: float(f.get("forecast_pm25_ugm3", current_pm25))) if forecast_list else {"hour_ahead": 3, "forecast_pm25_ugm3": current_pm25}
    best_h = min_fc.get("hour_ahead", 3)
    best_p25 = float(min_fc.get("forecast_pm25_ugm3", current_pm25))
    
    return {
        "tier": "TIER_3",
        "tier_name": "Tier 3 (No Meaningful Improvement in 6h - Indoor Recommended)",
        "recommended_park": best_park.get("name"),
        "best_park_obj": best_park,
        "best_hour": best_h,
        "best_pm25": best_p25,
        "current_band": best_park_cur_band,
        "current_pevi": best_park_cur_pevi,
        "improving_park": None,
        "improved_hour": None,
        "improved_band": None,
        "improved_pevi": None,
        "is_near_boundary": False,
        "boundary_margin": None
    }


# ─── Node 4: reason (Gemini API Integration) ─────────────────────────────────

def reason_node(state: AgentState) -> Dict[str, Any]:
    forecasts = state.get("forecast_data", [])
    parks = state.get("candidate_parks", [])
    pers_risk = state.get("personalized_risk_data", {})
    current_data = state.get("current_pevi_data", {})
    
    current_pm25 = float(current_data.get("pollutants", {}).get("pm25_ugm3", 28.8))
    compound_mult = float(pers_risk.get("multipliers", {}).get("total_compound_multiplier", 1.0))
    
    tier_info = evaluate_recommendation_tier(
        candidate_parks=parks,
        forecast_list=forecasts,
        current_pm25=current_pm25,
        compound_multiplier=compound_mult
    )
    
    tier = tier_info["tier"]
    best_park_name = tier_info["recommended_park"]
    best_hour = tier_info["best_hour"]
    best_pm25 = tier_info["best_pm25"]
    is_near_boundary = tier_info.get("is_near_boundary", False)
    
    if tier == "TIER_1":
        best_window = "Right now (Favorable outdoor conditions)"
    elif tier == "TIER_2":
        if is_near_boundary:
            best_window = f"In {best_hour} hour{'s' if best_hour > 1 else ''} (expected ~around {tier_info['improved_band']} levels, near boundary)"
        else:
            best_window = f"In {best_hour} hour{'s' if best_hour > 1 else ''} (Wait for window: improves to {tier_info['improved_band']})"
    else:
        best_window = f"In {best_hour} hour{'s' if best_hour > 1 else ''} (Lowest PM2.5: {best_pm25:.1f} ug/m³, but risk remains elevated)"

    gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    reasoning_summary = {}

    if gemini_api_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            llm = ChatGoogleGenerativeAI(
                model="gemini-3.6-flash",
                google_api_key=gemini_api_key,
                temperature=0.2
            )
            prompt = f"""
You are HawaGuide AI, an intelligent environmental spatial agent for Delhi NCR.
Analyze the following user profile, environmental forecast, and 3-Tier recommendation classification:

USER PROFILE:
- Age Group: {state.get('age_group')}
- Conditions: {state.get('conditions')}
- Smoker: {state.get('smoker')}
- Planned Activity: {state.get('planned_activity')}
- Planned Duration: {state.get('duration_hours')} hours
- Compound Multiplier: {compound_mult:.3f}x

ENVIRONMENTAL DATA:
- Starting Location Base PEVI: {current_data.get('pevi_value')} (Current PM2.5: {current_pm25} ug/m³)
- 6-Hour PM2.5 Forecast Trajectory: {forecasts}
- Evaluated Tier: {tier_info['tier_name']}
- Target Park: {best_park_name}
- Tier Metrics: {tier_info}
- Near Boundary Caveat: {is_near_boundary}

TONE AND DIRECTIVENESS GUIDELINES:
- Use an advisory, supportive, consumer-friendly tone (AirVisual/AirLief style), NOT medical commands.
- For TIER 1: Recommend going now normally without caveats.
- For TIER 2: Suggest considering waiting until the better window. If 'is_near_boundary' is True (projected PEVI is close to the threshold like 7.67 vs 7.70), soften the transition (e.g., 'conditions are expected to improve to around Moderate levels in X hours, though this is close to the boundary and actual conditions may vary') rather than an absolute guarantee.
- For TIER 3: Transparently advise that waiting in the next 6h won't meaningfully help, and suggest indoor activities or checking back later.

TASK:
Provide a concise 2-sentence rationale synthesizing this analysis following the exact advisory rules for {tier}.
"""
            response = llm.invoke([HumanMessage(content=prompt)])
            
            if isinstance(response.content, str):
                gemini_text = response.content.strip()
            elif isinstance(response.content, list):
                gemini_text = "".join([c.get("text", "") if isinstance(c, dict) else str(c) for c in response.content]).strip()
            else:
                gemini_text = str(response.content).strip()

            reasoning_summary = {
                "llm_engine": "gemini-3.6-flash",
                "tier": tier,
                "tier_name": tier_info["tier_name"],
                "recommended_park": best_park_name,
                "best_time_window": best_window,
                "gemini_analysis": gemini_text,
                "tier_info": tier_info
            }
        except Exception as e:
            logging.warning(f"Gemini API invocation fallback: {e}")
            if tier == "TIER_1":
                rationale_text = f"Conditions at {best_park_name} are currently favorable for your profile."
            elif tier == "TIER_2":
                if is_near_boundary:
                    rationale_text = f"Consider waiting {best_hour} hours when conditions at {tier_info['improving_park']} are expected to improve to around {tier_info['improved_band']} levels, though close to the boundary."
                else:
                    rationale_text = f"Consider waiting {best_hour} hours when conditions at {tier_info['improving_park']} improve to {tier_info['improved_band']}."
            else:
                rationale_text = f"Conditions remain elevated for all 6 hours; {best_park_name} is least-risky if necessary, but indoor activity is recommended."
            
            reasoning_summary = {
                "llm_engine": "heuristic_fallback",
                "tier": tier,
                "tier_name": tier_info["tier_name"],
                "recommended_park": best_park_name,
                "best_time_window": best_window,
                "rationale": rationale_text,
                "tier_info": tier_info
            }
    else:
        if tier == "TIER_1":
            rationale_text = f"Conditions at {best_park_name} are currently favorable for your profile."
        elif tier == "TIER_2":
            if is_near_boundary:
                rationale_text = f"Consider waiting {best_hour} hours when conditions at {tier_info['improving_park']} are expected to improve to around {tier_info['improved_band']} levels, though close to the boundary."
            else:
                rationale_text = f"Consider waiting {best_hour} hours when conditions at {tier_info['improving_park']} improve to {tier_info['improved_band']}."
        else:
            rationale_text = f"Conditions remain elevated for all 6 hours; {best_park_name} is least-risky if necessary, but indoor activity is recommended."

        reasoning_summary = {
            "llm_engine": "heuristic_engine",
            "tier": tier,
            "tier_name": tier_info["tier_name"],
            "recommended_park": best_park_name,
            "best_time_window": best_window,
            "rationale": rationale_text,
            "tier_info": tier_info
        }

    trace_entry = {
        "node": "reason",
        "description": "Synthesized multi-objective reasoning over forecast trajectory and candidate green spaces",
        "data": reasoning_summary
    }
    existing_trace = list(state.get("node_trace", []))
    existing_trace.append(trace_entry)
    return {
        "reasoning_analysis": reasoning_summary,
        "node_trace": existing_trace
    }


# ─── Node 5: explain ─────────────────────────────────────────────────────────

def explain_node(state: AgentState) -> Dict[str, Any]:
    reasoning = state.get("reasoning_analysis", {})
    tier_info = reasoning.get("tier_info", {})
    tier = tier_info.get("tier", "TIER_3")
    
    best_park = tier_info.get("best_park_obj") or (state.get("candidate_parks", [{}])[0] if state.get("candidate_parks") else {})
    park_name = best_park.get("name", "the recommended green space")
    dist_km = float(best_park.get("distance_km", 5.0))
    park_pers_pevi = float(best_park.get("personalized_pevi", 8.0))
    park_risk_band = best_park.get("personalized_risk_band", "Moderate (Band 2)")
    park_advisory = best_park.get("advisory_guidance", "Acceptable conditions for outdoor activities.")
    
    conds_str = ", ".join(state.get("conditions", []) or ["general"])
    profile_str = f"{state.get('age_group')}, {conds_str}, {state.get('duration_hours')}h {state.get('planned_activity')}"
    
    best_hour = tier_info.get("best_hour", 3)
    best_pm25 = float(tier_info.get("best_pm25", 17.7))
    is_near_boundary = tier_info.get("is_near_boundary", False)

    if tier == "TIER_1":
        # TIER 1: Best park is Low/Moderate risk right now -> Recommend going now, normally, no caveats
        explanation = (
            f"For your profile ({profile_str}), we recommend visiting "
            f"**{park_name}** ({dist_km:.1f} km away) right now (Personalized PEVI: {park_pers_pevi:.2f}, {park_risk_band}). "
            f"Conditions are favorable for outdoor activity. "
            f"{park_advisory}"
        )
    elif tier == "TIER_2":
        # TIER 2: Best park is High/Extreme now, BUT crosses into Low/Moderate (or better band) -> Lead with advisory wait instruction
        impr_park = tier_info.get("improving_park", park_name)
        impr_h = tier_info.get("improved_hour", best_hour)
        impr_band = tier_info.get("improved_band", "Moderate (Band 2)")
        impr_pevi = float(tier_info.get("improved_pevi", park_pers_pevi))
        cur_band = tier_info.get("current_band", park_risk_band)
        cur_pevi = float(tier_info.get("current_pevi", park_pers_pevi))
        time_phrase = f"{impr_h} hour from now" if impr_h == 1 else f"{impr_h} hours from now"
        
        if is_near_boundary:
            explanation = (
                f"Consider waiting until {time_phrase}, when conditions at **{impr_park}** "
                f"are expected to improve to around {impr_band} levels (Personalized PEVI expected ~{impr_pevi:.2f}), "
                f"though this is close to the {cur_band} boundary and actual conditions may vary. "
                f"Going now would mean {cur_band} exposure (Personalized PEVI: {cur_pevi:.2f} at {park_name})."
            )
        else:
            explanation = (
                f"Consider waiting until {time_phrase}, when **{impr_park}** "
                f"improves to {impr_band} (Personalized PEVI expected ~{impr_pevi:.2f}). "
                f"Going now would mean {cur_band} exposure (Personalized PEVI: {cur_pevi:.2f} at {park_name})."
            )
    else:
        # TIER 3: Best park is High/Extreme now AND stays that way for all 6h -> Honest advice that waiting won't help enough
        explanation = (
            f"Outdoor conditions aren't favorable for your profile right now, and conditions aren't expected to improve enough in the next 6 hours. "
            f"If you must go out, **{park_name}** ({dist_km:.1f} km away) is the least-risky option (Personalized PEVI: {park_pers_pevi:.2f}, {park_risk_band}), "
            f"but consider indoor activities or checking back later today instead. "
            f"The lowest-exposure window is in {best_hour} hours (PM2.5 forecasted at {best_pm25:.1f} ug/m³), though conditions remain in {park_risk_band}."
        )

    trace_entry = {
        "node": "explain",
        "description": "Formatted plain-language consumer advisory recommendation tailored to the recommended park",
        "data": {
            "tier": tier,
            "recommended_park": park_name,
            "park_personalized_pevi": park_pers_pevi,
            "park_risk_band": park_risk_band,
            "is_near_boundary": is_near_boundary,
            "recommendation_text": explanation
        }
    }
    existing_trace = list(state.get("node_trace", []))
    existing_trace.append(trace_entry)
    return {
        "recommendation_text": explanation,
        "node_trace": existing_trace
    }


# ─── Build StateGraph ────────────────────────────────────────────────────────

def create_agent_graph() -> StateGraph:
    workflow = StateGraph(AgentState)

    workflow.add_node("fetch_current", fetch_current_node)
    workflow.add_node("fetch_forecast", fetch_forecast_node)
    workflow.add_node("personalize", personalize_node)
    workflow.add_node("reason", reason_node)
    workflow.add_node("explain", explain_node)

    workflow.set_entry_point("fetch_current")
    workflow.add_edge("fetch_current", "fetch_forecast")
    workflow.add_edge("fetch_forecast", "personalize")
    workflow.add_edge("personalize", "reason")
    workflow.add_edge("reason", "explain")
    workflow.add_edge("explain", END)

    return workflow.compile()


# Singleton compiled graph instance
agent_app = create_agent_graph()


def run_agent_recommendation(
    lat: float,
    lon: float,
    age_group: str = "adult",
    conditions: Optional[List[str]] = None,
    smoker: bool = False,
    planned_activity: str = "moderate",
    duration_hours: float = 1.0,
    alpha: float = 0.5
) -> Dict[str, Any]:
    """
    Executes the compiled LangGraph agent workflow and returns structured results and trace.
    """
    initial_state: AgentState = {
        "lat": lat,
        "lon": lon,
        "age_group": age_group,
        "conditions": conditions or [],
        "smoker": smoker,
        "planned_activity": planned_activity,
        "duration_hours": duration_hours,
        "alpha": alpha,
        "current_pevi_data": {},
        "forecast_data": [],
        "personalized_risk_data": {},
        "candidate_parks": [],
        "reasoning_analysis": {},
        "recommendation_text": "",
        "node_trace": []
    }

    final_state = agent_app.invoke(initial_state)

    best_park_obj = final_state.get("candidate_parks", [{}])[0] if final_state.get("candidate_parks") else {}

    return {
        "status": "success",
        "recommendation": final_state["recommendation_text"],
        "best_park": best_park_obj,
        "best_time_window": final_state.get("reasoning_analysis", {}).get("best_time_window"),
        "start_location_personalized_pevi": final_state.get("personalized_risk_data", {}).get("personalized_pevi"),
        "recommended_park_personalized_pevi": best_park_obj.get("personalized_pevi"),
        "recommended_park_risk_band": best_park_obj.get("personalized_risk_band"),
        "multipliers": final_state.get("personalized_risk_data", {}).get("multipliers"),
        "trace": final_state.get("node_trace", []),
        "disclaimer": MEDICAL_DISCLAIMER
    }
