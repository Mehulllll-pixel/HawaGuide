# HawaGuide o(*￣▽￣*)o

> **Hyperlocal Air Quality Intelligence & Personalized Exposure Vulnerability Index (PEVI) for Delhi NCR**

---

## Why HawaGuide?

India's official AQI reports only the single worst pollutant on a given day, ignoring the other 5. HawaGuide's PEVI instead adds up the real health-risk contribution from all 6 measured pollutants (PM2.5, PM10, NO2, SO2, O3, CO) together - so a location with several moderately-bad pollutants is correctly shown as riskier than standard AQI would suggest.

---

## Visual Overview & UI Walkthrough

### 1. Interactive Liquid Glass Main Landing Page
![Interactive Liquid Glass Main Landing Page](docs/screenshots/hero.png)
*Real-time Delhi NCR air quality atmosphere with live network PEVI widget, 6-hour trend preview, and quick explainer trigger.*

### 2. Hyperlocal Green Spaces & Personalized PEVI
![Hyperlocal Green Spaces & Personalized PEVI](docs/screenshots/location-cards.png)
*40 Delhi NCR parks ranked by health-weighted exposure index with real-time pollutant levels, tailored risk bands, and plain-language guidance.*

### 3. Diurnal Air Quality Forecast Rail
![Diurnal Air Quality Forecast Rail](docs/screenshots/forecast.png)
*6-hour dynamic forecast timeline highlighting optimal breathable windows for outdoor activity across the region.*

### 4. Conversational Air Quality Agent ("Hawa")
![Conversational Air Quality Agent](docs/screenshots/agent-chat.png)
*Autonomous LLM assistant with structured health profile clarification, personalized route advice, and live environmental intelligence.*

---

## System Overview

HawaGuide is an end-to-end environmental intelligence platform built on five core pillars:

1. **Continuous Regulatory Ingestion**: Ingests multi-pollutant measurements from regulatory monitoring networks (CPCB, DPCC, IMD, IITM, UPPCB, HSPCB) via the OpenAQ v3 API and persists spatial observations in PostGIS.
2. **Geostatistical Kriging to Green Spaces**: Uses Ordinary Kriging with empirical variogram modeling to interpolate continuous pollution surfaces across 40 urban parks.
3. **5-Factor Personalized Vulnerability (PEVI)**: Adjusts raw multi-pollutant ambient risk using individual demographic, physiological, respiratory/cardiac, and activity-duration multipliers.
4. **Multi-Horizon Trajectory Forecasting**: Generates 6-hour predictive trajectories using an evaluated 100% XGBoost v3 model conditioned on diurnal signals and lag dynamics.
5. **Conversational Intelligence**: An autonomous LangGraph agent powered by Google Gemini that extracts health constraints from natural language, resolves routes, and offers contextual recommendations.

---

## Project Architecture

```text
HawaGuide/
├── README.md                           # Project Documentation & Limitations
├── .gitignore                          # Repository ignores (venv, .env, __pycache__)
├── backend/
│   ├── .env                            # PostgreSQL & API Credentials
│   ├── .env.example                    # Environment variable template
│   ├── requirements.txt                # Python dependencies
│   ├── app/                            # FastAPI backend service (endpoints, PEVI APIs)
│   │   └── __init__.py
│   ├── data_pipeline/                  # Data ingestion & PostGIS management
│   │   ├── __init__.py
│   │   ├── schema.sql                  # PostGIS DDL schema & spatial indexes
│   │   ├── setup_db.py                 # Automated schema & extension initializer
│   │   ├── openaq_stations.py          # Active Delhi NCR station discovery & ingestion
│   │   └── openaq_readings.py          # 90-day hourly multi-pollutant measurements sync
│   ├── ml/                             # Geostatistical & ML models
│   │   ├── __init__.py
│   │   ├── kriging.py                  # Ordinary Kriging, LOOCV & 40-Park PEVI estimation
│   │   ├── pevi.py                     # 6-Pollutant PEVI calculation & risk banding
│   │   ├── forecast_xgboost.py         # Multi-horizon XGBoost training & evaluation
│   │   ├── forecast_engine.py          # Production multi-horizon trajectory engine
│   │   ├── optimizer.py                # Multi-objective spatial location optimizer
│   │   └── agent_graph.py              # LangGraph 5-node StateGraph workflow
│   └── tests/                          # Automated test suite (spatial, ML, agent)
├── docs/                               # Architecture notes & research papers
└── frontend/                           # React / Mapbox UI application
```

---

## Quickstart & Execution

### 1. Database Setup
Ensure PostgreSQL 18 with PostGIS 3.6 is running, configure `backend/.env`, and execute:
```powershell
.\venv\Scripts\python.exe backend/data_pipeline/setup_db.py
```

### 2. Discover Active Stations & Ingest OpenAQ Readings
```powershell
# Discover and register 14 active monitoring stations
.\venv\Scripts\python.exe backend/data_pipeline/openaq_stations.py

# Ingest 90 days of hourly multi-pollutant readings (~144,000 rows)
.\venv\Scripts\python.exe backend/data_pipeline/openaq_readings.py
```

### 3. Run Kriging Validation & 40-Park Interpolation
```powershell
.\venv\Scripts\python.exe backend/ml/kriging.py
```

### 4. Compute PEVI Scores & Rank 40 Parks
```powershell
.\venv\Scripts\python.exe backend/ml/pevi.py
```

### 5. Train & Evaluate 6-Hour Ahead PM2.5 Forecast Models
```powershell
# Train & evaluate multi-horizon XGBoost models
.\venv\Scripts\python.exe backend/ml/train_and_save_forecaster.py
```

### 6. Run Personalized Park Optimizer & Launch FastAPI Backend
```powershell
# Run the standalone location optimizer CLI test
.\venv\Scripts\python.exe backend/ml/optimizer.py

# Launch the FastAPI REST service on http://localhost:8000
.\venv\Scripts\uvicorn.exe backend.app.main:app --reload --port 8000
```

---

## 40 Configured Delhi NCR Green Spaces

Air quality estimates and Personalized Exposure Vulnerability Index scores are computed for 40 real, named urban green spaces and stored in the PostGIS `interpolated_locations` table:

1. **Lodhi Garden** (Central Delhi)
2. **Sunder Nursery** (Nizamuddin / South East)
3. **Nehru Park** (Chanakyapuri)
4. **Deer Park** (Hauz Khas)
5. **District Park Hauz Khas** (Hauz Khas)
6. **Sanjay Van** (Qutub Institutional Area)
7. **Garden of Five Senses** (Said-ul-Ajaib / Saket)
8. **Buddha Jayanti Park** (Central Ridge)
9. **Central Park** (Connaught Place)
10. **India Gate Lawns** (Central Delhi)
11. **Amrit Udyan (Mughal Gardens)** (Rashtrapati Bhavan)
12. **Millennium Indraprastha Park** (Sarai Kale Khan)
13. **Japanese Park (Swarna Jayanti)** (Rohini Sector 10)
14. **Rohini District Park** (Rohini Sector 9)
15. **Yamuna Biodiversity Park** (Wazirabad)
16. **Aravalli Biodiversity Park** (Vasant Kunj)
17. **Aravalli Biodiversity Park** (Gurugram)
18. **Leisure Valley Park** (Sector 29, Gurugram)
19. **Tau Devi Lal Biodiversity Park** (Sector 52, Gurugram)
20. **Biodiversity Park Okhla** (Kalindi Kunj)
21. **Okhla Bird Sanctuary** (Noida / Delhi Border)
22. **Meghdootam Park** (Sector 50, Noida)
23. **Noida Biodiversity Park** (Sector 91, Noida)
24. **Mansarovar Park** (Sector 38A, Noida)
25. **Smriti Van** (Sector 49, Noida)
26. **Asola Bhatti Wildlife Sanctuary** (Tughlakabad)
27. **Qudsia Bagh** (Civil Lines)
28. **Roshanara Bagh** (Shakti Nagar)
29. **Shalimar Bagh District Park** (North Delhi)
30. **Talkatora Gardens** (President's Estate)
31. **Mahavir Jayanti Park** (Ridge Road)
32. **National Rose Garden** (Chanakyapuri)
33. **Jahanpanah City Forest** (Alaknanda / Greater Kailash)
34. **Sanjay Lake Park** (Mayur Vihar)
35. **Swarna Jayanti Park Indirapuram** (Ghaziabad)
36. **City Forest Ghaziabad** (Raj Nagar Extension)
37. **Town Park Faridabad** (Sector 12, Faridabad)
38. **Badkhal Lake Eco Park** (Faridabad)
39. **Surajkund Green Complex** (Faridabad / Delhi Border)
40. **Coronation Park** (Burari Road / Kingsway Camp)

---

## LangGraph Agent Layer & Conversational Intelligence

The intelligent agent layer integrates geostatistical interpolation, ML forecasting, personalized risk modeling, and LLM reasoning into a cyclical **LangGraph StateGraph** workflow:

```mermaid
graph TD
    A[Start: User Profile & Location] --> B[fetch_current: Query Current PEVI & Pollutant Breakdown]
    B --> C[fetch_forecast: Generate 6h PM2.5 Trajectory]
    C --> D[personalize: Apply Inhalation Multipliers & Rank 40 Parks]
    D --> E[reason: Google Gemini Synthesizes Optimal Window & Green Space]
    E --> F[explain: Format Plain-Language Advisory Recommendation]
    F --> G[End: Structured Recommendation & State Trace]
```

### 1. Personalization Multipliers
* **`age_multiplier`**:
  * `1.3` for **children** (<18, higher ventilation-to-body-mass ratio and developing airways) or **elderly** (65+, diminished cardiovascular elasticity).
  * `1.0` for **adults** (general baseline).
* **`condition_multiplier`**:
  * `1.5` for underlying **respiratory** (asthma, COPD) or **cardiac** conditions.
  * `1.0` for **healthy** individuals.
* **`smoker_multiplier`**:
  * `1.25` for tobacco smokers, accounting for compromised mucociliary clearance and chronic baseline airway inflammation.
* **`activity_multiplier`**:
  * **Rest / Sedentary (1.0x)**: Basal minute-ventilation rate ~6-8 L/min.
  * **Moderate Exercise (1.3x)**: Brisk walking, light cycling (~20-30 L/min).
  * **Vigorous Exercise (1.6x)**: Running, high-intensity cardio (~45-65+ L/min), shifting to oral inhalation that bypasses nasal filtration *(US EPA Exposure Factors Handbook, Chapter 6)*.
* **`duration_multiplier`**:
  * `(1 + 0.15 * duration_hours)` accounts for cumulative inhaled dose over time.

> [!NOTE]
> **Epidemiological Attribution & Literature Basis**:
> These multipliers are informed by:
> 1. US EPA *"Particle Pollution Exposure"* clinical references on sensitive subpopulations.
> 2. Time-series epidemiological studies on ambient air pollution and vulnerable group hospitalizations (e.g., a Southwest China multi-city time-series study on air pollution and elderly asthma hospitalization, *PMC10859495*).
> 
> *Disclaimer*: While grounded in EPA sensitive-group categorizations and published relative-risk ranges, these specific constants (1.3, 1.5, 1.25, 0.15/hr) represent HawaGuide's own engineering and risk-weighting framework for comparative green space ranking, not directly published universal constants.

---

### 2. Multi-Objective Spatial Location Optimizer

For any user starting coordinate (lat, lon), the optimizer balances **environmental pollution risk** against **travel distance**:

1. **Geodetic Proximity via PostGIS**:
   Computes geodesic distances from user coordinates to all 40 parks using PostGIS `ST_Distance(location::geography, ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography)`.
2. **Min-Max Feature Normalization**:
   Normalizes both `Personalized_PEVI` and `distance_km` across all 40 candidate parks to a `[0, 1]` scale:
   ```text
   norm_risk     = (risk - min(risk)) / (max(risk) - min(risk))
   norm_distance = (dist - min(dist)) / (max(dist) - min(dist))
   ```
3. **Composite Trade-Off Scoring**:
   ```text
   Score = alpha * norm_risk + (1 - alpha) * norm_distance    (lower is better)
   ```
   * `alpha = 1.0` -> Purely lowest pollution risk.
   * `alpha = 0.0` -> Purely closest geographic proximity.
   * `alpha = 0.5` -> Balanced health-travel trade-off.

---

### 3. FastAPI Endpoint: `POST /agent/recommend`

#### Request Schema:
```json
{
  "lat": 28.6328,
  "lon": 77.2197,
  "age_group": "elderly",
  "conditions": ["asthma"],
  "smoker": false,
  "planned_activity": "moderate",
  "duration_hours": 2.0,
  "alpha": 0.6
}
```

#### Response Structure:
Returns the final plain-language recommendation text, the optimal time window in the next 6 hours, top recommended park, compound multiplier breakdown, complete 5-node state trace (with input/output snapshots at each node for auditability), and the standard medical disclaimer.

---

### 4. FastAPI Endpoint: `POST /agent/ask` (Conversational, Session-Aware)

A natural-language conversational interface built on top of the same LangGraph workflow. Accepts free-text messages and maintains per-session slot memory across turns — so users do not need to fill a structured JSON form.

#### How it works

```text
Turn N  →  load partial state for session_id
        →  Gemini structured-output call: extract {age_group, conditions, smoker,
                                             planned_activity, duration_hours, location}
        →  Nominatim geocoding: location name → (lat, lon)
        →  merge into session state
        →  still missing fields? → return clarifying question  (status: "clarifying")
        →  all fields present?  → run full LangGraph agent    (status: "complete")
```

#### Request Schema:
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Is it safe to go outside right now? I'm elderly with asthma.",
  "alpha": 0.6
}
```

#### Response Schema:
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "clarifying",
  "message": "To give you a personalised recommendation, I still need a few details: location, whether you smoke (yes / no), planned activity level (rest / moderate / vigorous), and how long you plan to be outside (e.g. 1 hour, 1.5 hours).",
  "missing_fields": ["location", "whether you smoke (yes / no)", "planned activity level (rest / moderate / vigorous)", "how long you plan to be outside (e.g. 1 hour, 1.5 hours)"],
  "extraction_degraded": false,
  "recommendation": null,
  "disclaimer": "This tool provides general environmental air quality guidance, not medical advice; consult a healthcare provider for personal health decisions."
}
```

**`extraction_degraded`**: `true` when the Gemini field-extraction call failed (quota, outage). In that case the question is prefixed honestly: *"I'm having trouble understanding free-text right now, so please share each detail separately: ..."*

Session state is cleared after a successful recommendation, so the next message with the same `session_id` starts a fresh conversation naturally.

---

### 5. API Key & Quota: Same Key, Shared Pool

> [!IMPORTANT]
> **Both `/agent/recommend` (Gemini reasoning node) and `/agent/ask` (Gemini field-extraction) load the same `GEMINI_API_KEY` from `backend/.env`.**
>
> - `main.py` resolves `Path(__file__).resolve().parent.parent / ".env"` → `backend/.env`
> - `agent_graph.py` tries `PROJECT_ROOT / "backend" / ".env"` first → `backend/.env`
>
> Both paths resolve to the same file. All Gemini calls from a running uvicorn process draw from the **same daily quota**.

> [!CAUTION]
> **Free-tier quota**: The Gemini free tier allows **20 requests per day per model** (`gemini-3.6-flash`).
> Each full conversational turn via `/agent/ask` uses **2 quota slots** — 1 for field extraction + 1 for the reasoning node.
> That means the free tier supports approximately **10 full conversational recommendations per day** under normal use.
> For sustained production use or load testing, upgrade to a paid Gemini API plan (Pay-as-you-go or Vertex AI) to remove the daily cap.

---

## Technical Deep-Dive & ML/Geostatistical Methodology

### 1. Core Geostatistical Modeling: Ordinary Kriging

HawaGuide employs **Ordinary Kriging (OK)** using a spherical variogram model to interpolate continuous concentration fields for 6 key air pollutants:
- **Particulate Matter**: PM2.5, PM10
- **Gaseous Pollutants**: NO2, SO2, O3, CO

#### Cross-Validation Methodology
Model performance is evaluated via **Leave-One-Station-Out Cross-Validation (LOOCV)** across **100 randomly sampled hourly timestamps** spanning the 90-day historical archive (~1,400 individual model fits):

| Pollutant | Sample Runs | Avg Stations Reporting | Mean Actual Value | Mean LOOCV RMSE | RMSE Std. Dev (σ) | Mean LOOCV MAE | Relative Error |
|---|---|---|---|---|---|---|---|
| **PM2.5** | 100 | 13.1 | 44.78 µg/m³ | **25.88 µg/m³** | ± 35.91 | 18.33 µg/m³ | **54.7%** |
| **PM10** | 100 | 13.1 | 133.17 µg/m³ | **61.65 µg/m³** | ± 39.91 | 45.50 µg/m³ | **49.0%** |
| **NO2** | 100 | 13.3 | 29.31 µg/m³ | **22.12 µg/m³** | ± 10.21 | 17.02 µg/m³ | **75.2%** |
| **SO2** | 100 | 7.5 | 18.62 µg/m³ | **13.15 µg/m³** | ± 6.74 | 11.04 µg/m³ | **69.0%** |
| **O3** | 100 | 13.1 | 27.96 µg/m³ | **21.83 µg/m³** | ± 15.57 | 16.63 µg/m³ | **79.1%** |
| **CO** | 100 | 13.4 | 0.85 mg/m³ | **0.56 mg/m³** | ± 0.24 | 0.42 mg/m³ | **67.1%** |

---

### 2. Personalized Exposure Vulnerability Index (PEVI) Formulation

The **Personalized Exposure Vulnerability Index (PEVI)** is a continuous, multipollutant exposure and health vulnerability metric calculated across all 40 urban green spaces in Delhi NCR. It quantifies the combined excess health risk from concurrent inhalation of 6 key air pollutants.

#### Published Base Formulation: Canada AQHI (Stieb et al. 2008)
The foundational risk-additive mathematical structure directly adopts the peer-reviewed **Air Quality Health Index (AQHI)** methodology established by Health Canada and Environment Canada:

> **Citation**: Stieb, D. M., Burnett, R. T., Smith-Doiron, M., Brion, O., Shin, H. H., & Economou, V. (2008). *"A New Multipollutant, No-Threshold Air Quality Health Index Based on Short-Term Mortality Risk in Canadian Cities."* Journal of the Air & Waste Management Association, 58(3), 435–450. [DOI: 10.3155/1047-3289.58.3.435](https://doi.org/10.3155/1047-3289.58.3.435)

The published 3-pollutant base formula is:

$$
\text{AQHI}_{\text{base}} = \left(\frac{10}{10.4}\right) \times 100 \times \left[ \left(e^{0.000537 \times \text{O}_3} - 1\right) + \left(e^{0.000871 \times \text{NO}_2} - 1\right) + \left(e^{0.000487 \times \text{PM}_{2.5}} - 1\right) \right]
$$

* **Input Units**: $\text{O}_3$ and $\text{NO}_2$ in $\text{ppb}$; $\text{PM}_{2.5}$ in $\mu\text{g/m}^3$.
* **Unit Conversion**: Because HawaGuide's PostGIS database stores ambient gas concentrations in $\mu\text{g/m}^3$, standard **EPA atmospheric reference conversion factors** (at $25^\circ\text{C}$, $1\text{ atm}$, molar volume $V_m = 24.45\text{ L/mol}$) are applied prior to exponential risk calculation:

$$
\text{O}_3\ (\text{ppb}) = \text{O}_3\ (\mu\text{g/m}^3) \times \frac{24.45}{47.998} \approx \text{O}_3 \times 0.50940
$$

$$
\text{NO}_2\ (\text{ppb}) = \text{NO}_2\ (\mu\text{g/m}^3) \times \frac{24.45}{46.005} \approx \text{NO}_2 \times 0.53146
$$

---

#### HawaGuide Multipollutant Extension (PM10, SO2, CO)

> [!NOTE]
> **Attribution & Non-Peer-Reviewed Scope**: The risk terms for $\text{PM}_{10}$, $\text{SO}_2$, and $\text{CO}$ represent a **custom engineering extension developed specifically for HawaGuide**. They are **explicitly separate from the original published Canadian AQHI model** (Stieb et al. 2008), which was calibrated on a 3-pollutant mortality dataset.

To account for Delhi NCR's severe coarse dust episodes ($\text{PM}_{10}$), industrial sulfur emissions ($\text{SO}_2$), and vehicular combustion ($\text{CO}$), equivalent exponential excess-risk terms are derived by scaling relative to the **WHO 2021 Air Quality Guideline** thresholds (stricter benchmark implies higher assumed biological risk coefficient):

$$
\beta_{\text{pollutant}} = \beta_{\text{PM}_{2.5}} \times \left( \frac{\text{Guideline}_{\text{PM}_{2.5}}}{\text{Guideline}_{\text{pollutant}}} \right)
$$

| Pollutant | Stored Unit | WHO Guideline Threshold | Guideline Ratio vs PM2.5 | Derived Excess Risk Coefficient ($\beta$) | Source / Formulation |
|---|---|---|---|---|---|
| **O3** | $\mu\text{g/m}^3 \to \text{ppb}$ | $100\ \mu\text{g/m}^3$ (8-hr) | — | $\mathbf{0.000537}\ \text{ppb}^{-1}$ | Published (Stieb et al. 2008) |
| **NO2** | $\mu\text{g/m}^3 \to \text{ppb}$ | $25\ \mu\text{g/m}^3$ (24-hr) | — | $\mathbf{0.000871}\ \text{ppb}^{-1}$ | Published (Stieb et al. 2008) |
| **PM2.5** | $\mu\text{g/m}^3$ | $15\ \mu\text{g/m}^3$ (24-hr) | $1.000$ | $\mathbf{0.000487}\ (\mu\text{g/m}^3)^{-1}$ | Published (Stieb et al. 2008) |
| **PM10** | $\mu\text{g/m}^3$ | $45\ \mu\text{g/m}^3$ (24-hr) | $15 / 45 = 0.333$ | $\mathbf{0.000162}\ (\mu\text{g/m}^3)^{-1}$ | HawaGuide Extension |
| **SO2** | $\mu\text{g/m}^3$ | $40\ \mu\text{g/m}^3$ (24-hr) | $15 / 40 = 0.375$ | $\mathbf{0.000183}\ (\mu\text{g/m}^3)^{-1}$ | HawaGuide Extension |
| **CO** | $\text{mg/m}^3$ | $4.0\ \text{mg/m}^3$ (8-hr) | $(15 \times 0.000487) / 4.0$ | $\mathbf{0.001826}\ (\text{mg/m}^3)^{-1}$ | HawaGuide Extension |

#### Complete PEVI Equation

$$
\text{PEVI} = \left(\frac{10}{10.4}\right) \times 100 \times \left[ \sum_{p \in \{\text{O}_3, \text{NO}_2, \text{PM}_{2.5}\}} \left(e^{\beta_p C_p} - 1\right) + \sum_{q \in \{\text{PM}_{10}, \text{SO}_2, \text{CO}\}} \left(e^{\beta_q C_q} - 1\right) \right]
$$

---

### 3. CO Data Quality Audit & Unit Correction in Indian Regulatory Feeds

During development of the PEVI pipeline, a rigorous unit and magnitude validation was conducted on the OpenAQ v3 data ingested from Indian monitoring stations (CPCB/DPCC):

* **Observed Inconsistency**: OpenAQ v3 sensor metadata lists active CPCB CO sensors under `units="ppb"` (e.g., sensor `12234748` at ITO).
* **Magnitude Sanity Check**: Ingested CO numerical values range between **0.10 and 6.0 mg/m³** (with peak localized spikes up to 43.0). If these numbers were truly in ppb, ambient CO across Delhi would equal 0.0001 - 0.006 ppm — an impossibly clean reading that violates atmospheric chemistry baselines. In mg/m³, these values align precisely with Delhi's known ambient concentration range (0.5 - 3.0 mg/m³) and the WHO 8-hour benchmark (4.0 mg/m³).
* **Literature Context**: This reflects a documented unit-labeling inconsistency in Indian CPCB data transmitted via OpenAQ, where mass concentrations in mg/m³ are periodically ingested under volumetric ppb parameter tags (see *Vohra et al., Science of The Total Environment*, ScienceDirect, on data quality and unit reporting anomalies across Indian air quality networks).
* **Implementation Fix**: HawaGuide explicitly treats and processes all CO readings as **mg/m³**, utilizing the WHO-calibrated coefficient $\beta_{\text{CO}} = 0.001826\ (\text{mg/m}^3)^{-1}$.

---

### 4. Hotspot Proximity Correlation: Evaluating Spatial Smoothing

To evaluate whether proximity to localized high-emission monitors skews park vulnerability scores or creates sharp distance-decay artifacts, great-circle distances were computed from each of the 40 parks to Delhi's two primary industrial/transit monitoring hotspots: **Anand Vihar** (DPCC) and **Punjabi Bagh** (DPCC):

* **Statistical Correlations (All 40 Urban Parks)**:
  * **Distance to Nearest Hotspot vs. PEVI**: Pearson $r = -0.2844$ (Weak inverse correlation), Spearman $\rho = -0.2668$
  * **Distance to Anand Vihar vs. PEVI**: Pearson $r = -0.1004$ ($p = 0.54$, virtually uncorrelated), Spearman $\rho = +0.0008$
  * **Distance to Punjabi Bagh vs. PEVI**: Pearson $r = -0.7946$ ($p = 9.25 \times 10^{-10}$), Spearman $\rho = -0.8143$

* **Sensitivity & Robustness Analysis of the Punjabi Bagh Correlation ($N=40$)**:
  * **Distance Range**: $4.2\text{ km}$ (Rohini District Park) to $35.8\text{ km}$ (Town Park Faridabad), mean distance $16.9\text{ km}$.
  * **Outlier & Boundary Sensitivity Checks**:
    * Removing the 3 farthest parks (Faridabad / Ghaziabad, $N=37$): Pearson $r = -0.8529$, Spearman $\rho = -0.8390$.
    * Removing the 3 closest parks (Rohini / Shalimar Bagh, $N=37$): Pearson $r = -0.8468$, Spearman $\rho = -0.8637$.
    * Leave-one-out sensitivity testing yields a maximum $\Delta r \le 0.034$ across all 40 parks, confirming the correlation is not an artifact driven by extreme leverage outliers.
  * **Driver of the Difference (Macro Regional Gradient vs. Local Plume)**:
    * Punjabi Bagh ($28.674^\circ\text{N}, 77.131^\circ\text{E}$) is located in the **North-Western corner** of Delhi NCR.
    * The underlying regional pollution surface exhibits a broad Northwest-to-Southeast macro-gradient (PEVI correlates with Latitude at $r = +0.4638$ and with Longitude at $r = -0.4931$).
    * Because Punjabi Bagh sits at the high-concentration terminus of this regional gradient, radial distance from Punjabi Bagh strongly co-varies with the broader macro-gradient across Delhi NCR.
    * In contrast, Anand Vihar ($28.648^\circ\text{N}, 77.316^\circ\text{E}$) is located on the Eastern border, directly adjacent to cleaner East/South-East peripheral parks (e.g. *Smriti Van* at $\text{PEVI} = 3.38$, *Meghdootam Park* at $\text{PEVI} = 3.45$, located $7.9 - 8.2\text{ km}$ away) while central parks $12+\text{ km}$ to the west have higher baseline vulnerability ($5.5 - 6.5$).

* **Physical & Geostatistical Interpretation**:
  * Cleanest, lowest-vulnerability parks in the East/South-East periphery remain low-risk despite being within $8\text{ km}$ of Anand Vihar, while central parks further away experience elevated exposure.
  * **Synthesis**: This is consistent with Ordinary Kriging's known spatial smoothing behavior (regression toward the regional background mean across the convex hull), though a correlation this weak alone doesn't prove causation — it serves as one piece of supporting empirical evidence alongside the underlying Gaussian random field mathematical formulation.

---

### 5. PEVI-Adjusted Relative Vulnerability Bands (Base vs. Personalized Scales)

> [!WARNING]
> **Scale Differentiation**: **Base PEVI** and **Personalized PEVI** operate on fundamentally different numerical scales and **must NOT use the same risk band cutoffs**:
> * **Base PEVI** represents ambient multi-pollutant vulnerability at the park location (unscaled baseline range: **3.12 - 7.07**).
> * **Personalized PEVI** incorporates demographic susceptibility, cardiopulmonary multipliers, and cumulative duration scaling (1.075x - 3.12x), expanding the score range to **3.59 - 18.0+**.

#### Base PEVI Quartile Bands (Ambient Green Space Risk)
Derived from the unweighted 40-park baseline distribution:

| Relative Vulnerability Band | Base PEVI Range (Quartiles) | Number of Parks | Illustrative Parks in Delhi NCR |
|---|---|---|---|
| **Band 1: Low Relative Vulnerability** | Base PEVI <= 4.13 (Q1) | 10 | Mansarovar Park (3.12), Okhla Bird Sanctuary (3.26), Smriti Van (3.38), Noida Biodiversity Park (3.53) |
| **Band 2: Moderate Relative Vulnerability** | 4.13 < Base PEVI <= 4.81 (Q2) | 10 | Leisure Valley Park (4.15), Town Park Faridabad (4.18), City Forest Ghaziabad (4.31), Sanjay Van (4.74) |
| **Band 3: High Relative Vulnerability** | 4.81 < Base PEVI <= 5.65 (Q3) | 10 | Jahanpanah City Forest (4.79), Deer Park (5.13), Sunder Nursery (5.14), Lodhi Garden (5.60) |
| **Band 4: Highest Relative Vulnerability** | Base PEVI > 5.65 (Q4) | 10 | Nehru Park (5.70), Central Park (6.16), Amrit Udyan (6.23), Talkatora Gardens (6.43), Roshanara Bagh (7.07) |

#### Personalized PEVI Relative Risk Bands (Individual Inhaled Burden)
Derived from the empirical pooled distribution across representative demographic personas ($N=160$ across 4 sensitivity tiers):

| Personalized Risk Band | Personalized PEVI Range | Consumer Advisory Guidance (AirLief / AirVisual Style) |
|---|---|---|
| **Band 1: Low Risk** | Pers PEVI <= 6.00 (Q1) | Great conditions for outdoor activities and exercise. |
| **Band 2: Moderate Risk** | 6.00 < Pers PEVI <= 7.70 (Q2) | Acceptable for most outdoor activities; sensitive groups may want to consider shorter outdoor sessions. |
| **Band 3: High Risk** | 7.70 < Pers PEVI <= 10.30 (Q3) | Higher air pollution exposure; sensitive groups may want to reduce strenuous outdoor activity or consider mask protection. |
| **Band 4: Extreme Risk** | Pers PEVI > 10.30 (Q4) | Significantly elevated exposure; consider indoor activities or choosing a lower-risk nearby location. |

> [!CAUTION]
> **Health Disclaimer**: This tool provides general environmental air quality guidance, not medical advice; consult a healthcare provider for personal health decisions.

---

### 6. Seasonal Meteorological Context (Monsoon vs. Winter Smog)

> [!IMPORTANT]
> **Pre-Monsoon / Monsoon Dataset Scope**: The underlying 90-day archive spans **June through September**.
> * During this season, continuous monsoon rainfall, convective atmospheric mixing, and active wet deposition wash out particulate matter, yielding Delhi's annual minimum background concentrations (mean PM2.5 ~ 44.8 µg/m³, mean PM10 ~ 133.2 µg/m³).
> * The resulting "mostly Moderate" PEVI scores (3.1 - 7.1) accurately reflect this **cleaner monsoon baseline** and must **not** be misinterpreted as underestimating Delhi's chronic winter pollution crisis.
> * During Delhi's severe winter smog period (**October through January**), characterized by nocturnal thermal inversions, calm winds, and stubble burning plumes, PM2.5 regularly surges 5x - 10x higher (300 - 500+ µg/m³), which will scale PEVI scores well into extreme advisory brackets (10+ to 20+).

---

## Known Limitations & Engineering Tradeoffs

> [!NOTE]
> For an honest, categorized breakdown of deliberately deferred improvements and architectural choices (spatial covariates, external drift kriging, boundary layer data, dynamic tool orchestration, production session stores), see [docs/FUTURE_IMPROVEMENTS.md](docs/FUTURE_IMPROVEMENTS.md).

> [!IMPORTANT]
> The spatial smoothing behavior of Ordinary Kriging is an **intentional, mathematically intrinsic tradeoff** of Gaussian random field regression, rather than an unexplained algorithmic flaw.

### 1. Linear Weighted-Average Constraint (Regression to the Mean)
Ordinary Kriging calculates unmonitored location values as a best linear unbiased estimator:

$$
\hat{Z}(x_0) = \sum_{i=1}^n \lambda_i Z(x_i), \quad \text{subject to } \sum_{i=1}^n \lambda_i = 1
$$

Because all weights sum to 1 and negative weights are mathematically bounded, Kriging operates as a **convex hull spatial smoothing operator**. It **cannot extrapolate or predict values more extreme** than its surrounding observation points.

### 2. Systematic Underestimation at Localized Emission Hotspots
In metropolitan Delhi NCR, air pollution is heavily influenced by micro-scale sources (congested transit hubs, industrial clusters, unpaved corridors, waste burning). When a localized high-emission monitor (such as Anand Vihar or Punjabi Bagh) is surrounded by lower-concentration residential or background monitors:
- **Kriging regresses the hotspot prediction toward the regional background mean.**
- **Empirical Hotspot LOOCV Results**:
  - **Underestimation Frequency**: Peak pollution at hotspot stations is underestimated in **69.8% to 70.6%** of hourly timestamps.
  - **PM2.5 Hotspots (Anand Vihar, NSIT Dwarka, Sirifort)**: Average underestimation deficit of **+15.33 µg/m³** below ground truth during spikes.
  - **PM10 Hotspots (Anand Vihar, Sector-125 Noida, Punjabi Bagh)**: Average underestimation deficit of **+56.09 µg/m³** (a **17.4%** systemic deficit relative to actual ground measurements).

### 3. Why this Tradeoff is Chosen for HawaGuide
For regional park exposure estimation and Personalized Exposure Vulnerability Index (PEVI) calculation, this spatial smoothing is desirable:
- It eliminates spurious numerical instability and runaway artifacts between sparse monitors.
- It produces stable, continuous background concentration baselines across park polygons without over-attributing localized road-edge anomalies to expansive green spaces.

### 4. 24-Hour Rolling Mean for Park-Level Estimates
Park-level pollutant estimates (stored in `interpolated_locations`) are computed from each station's **24-hour rolling mean**, not the instantaneous latest reading.

**Why:** With only 14 monitoring stations across Delhi NCR, a single hourly snapshot provides too few lag pairs for pykrige to reliably fit three variogram parameters (nugget, sill, range). The auto-fitting optimizer frequently converges to a degenerate **pure-nugget solution** — placing ~100% of variance into noise and zero into spatial signal — which collapses every park's Kriging estimate to the identical station-network mean, erasing all spatial variation.

Averaging across the most recent 24 hours smooths transient single-sensor spikes, gives the variogram estimator a richer and more representative spatial covariance structure, and consistently produces non-degenerate fits with genuine spatial gradients across all six pollutants.

**Tradeoff:** This means the park estimates reflect a ~24-hour lagged picture of air quality rather than the past hour. For the PEVI use case — characterising a park's *typical* pollution exposure for route recommendations — this temporal smoothing is appropriate. For real-time alert thresholds, a separate single-snapshot index (outside PEVI) would be needed.

### 5. Free-Text LLM Extraction & Daily Quota Limits
* Free-text extraction in `POST /agent/ask` uses live Google Gemini calls with structured schema constraints rather than brittle regex or keyword heuristics.
* On the Google AI Studio free tier, API usage is bounded by a **20 request/day** per-model quota (`gemini-3.6-flash`).
* **Graceful Degradation**: If the Gemini API call fails (quota exhausted, network timeout, or upstream outage), the agent marks `extraction_degraded: true` and falls back cleanly to asking structured clarification questions, explicitly informing the user rather than guessing or silently failing.

### 6. Live Nominatim Geocoding & Rate Limits
* Location resolution uses live OpenStreetMap Nominatim geocoding (`nominatim.openstreetmap.org/search`) with proper `User-Agent` headers rather than hardcoded location lookup dictionaries.
* Nominatim enforces an operational rate limit of **1 request/second**. Rapid concurrent requests or automated test suites must respect this limit or implement caching to avoid HTTP 429 throttling.

### 7. Spatial Sensor Density & Kriging Smoothing
* Delhi NCR ambient pollution surfaces are interpolated from 14 active, high-fidelity OpenAQ/CPCB reference stations.
* While Ordinary Kriging provides statistically optimal linear unbiased estimation across regional park polygons, hyper-local microclimates (such as roadside vehicle emissions, micro-topography, or temporary point-source biomass burning) cannot be fully resolved at sub-kilometer resolution without dense low-cost sensor meshes.

### 8. Seasonal Training Distribution
* Historical sensor baselines and ML forecasters were trained on monsoon/post-monsoon meteorological conditions (PM2.5 ~ 40 - 100 µg/m³).
* Delhi's severe winter inversion events (PM2.5 > 300 - 600 µg/m³) represent distinct atmospheric regimes. Ongoing model recalibration is recommended as winter ground data ingests.

### 9. Personalized PEVI Multipliers & Medical Disclaimer
* Inhalation volume scaling (e.g., 1.3x moderate, 1.6x vigorous) and demographic vulnerability factors are grounded in US EPA Exposure Factors Handbook and published epidemiologic relative risks.
* These scores provide environmental risk prioritization, not deterministic medical diagnostics or clinical guidance.
