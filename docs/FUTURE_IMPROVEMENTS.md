# Future Improvements & Deferred Work

Honest documentation of real improvements identified during development, deliberately not built now, with the reasoning for each deferral.

## Spatial Modeling (Kriging)

**Regression Kriging / Kriging with External Drift**: Ordinary Kriging only uses distance between stations, which is why it can never predict a value more extreme than its neighbors (causing hotspot underestimation, already documented). The real fix is adding covariates - distance to nearest major road, traffic density, land-use type - so the model has genuine information to justify an extreme prediction near a real hotspot. Not built because it requires sourcing real covariate data (road network distances, traffic data) that doesn't currently exist in this project - swapping the algorithm alone would change nothing without that data.

**Alternative: covariate-based ML model (e.g. XGBoost) for spatial interpolation**: Same underlying fix as above via a different technique - a tree-based model trained on coordinates + real covariates could escape Kriging's "must average" constraint entirely. Same blocker: requires real covariate data not yet sourced.

**PEVI uncertainty display**: Currently PEVI is shown as one precise-looking number, but given Kriging's known 49-79% relative error and hotspot-underestimation bias, showing an uncertainty range (especially near known hotspots) would be more honest. Not built yet - a real, valuable addition for future UI work.

## Forecasting

**Boundary layer height and stubble-burning/fire data (NASA FIRMS)**: Identified as high-expected-payoff additions (boundary layer height directly affects pollution trapping; stubble burning is a major real contributor to Delhi pollution) but deliberately not pursued to prioritize finishing the core pipeline over further accuracy gains.

**Per-station forecasting models**: Only pooled (all-station) models were tested. Individual per-station models might capture station-specific patterns better, at the cost of less training data per model. Not tested due to time constraints.

**Temporal Fusion Transformer or similar**: A more advanced sequence architecture than LSTM, but confirmed to need substantially more training data than this project currently has to outperform simpler models - not worth pursuing without significantly more historical data.

## Agent Architecture

**Dynamic tool selection (genuine autonomous agent behavior)**: The current LangGraph pipeline runs a FIXED sequence of steps every time (fetch_current -> fetch_forecast -> personalize -> reason -> explain). A genuinely autonomous agent would have the LLM decide which tools to call and in what order based on the situation. This is an honestly identified gap - free-text understanding was added as a real improvement, but dynamic tool orchestration was not built.

**Persistent, production-grade session storage**: Session state (_SESSIONS dictionary) currently lives only in server memory - it's wiped on every server restart and wouldn't work correctly across multiple server instances in a real scaled deployment. A production fix would use Redis or a database table for session storage. Not built because the project isn't yet deployed at a scale where this matters, but this is a REAL limitation to fix before genuine production use, not just a nice-to-have.

**Real user accounts**: Deliberately NOT built (chose localStorage-only profile memory instead) - a considered decision, not an oversight. Tying health/personalization data to a persistent, identifiable account is a real step up in privacy responsibility that wasn't justified for this project's current scope.

## UX / Features Discussed but Not Built

- Voice input (Web Speech API)
- Hindi/English language toggle
- Direct park-to-park comparison mode via chat
- Wait-time browser notification reminders
- "Explain why" expandable reasoning breakdown under each recommendation

## Infrastructure (Deprioritized Per Original Scope)

- Neo4j graph database (was planned to replace the plain distance-based optimizer)
- Kubernetes (explicit stretch goal, cuttable without any real loss)
