# Pakistan Flood Risk Monitor — Implementation Plan

**Purpose of this document:** this is a build spec for Claude Code (or any engineer) to implement the full system. It assumes the ML model has been trained separately in a Kaggle notebook (see companion file `flood_segmentation_training.ipynb`) and the trained weights are already available before backend work begins.

---

## 1. Project Overview

A mobile app that shows a live, district-level flood risk score for Pakistan's most flood-vulnerable districts, by fusing three signals:

1. **Satellite-observed water extent** — a fine-tuned geospatial foundation model (Prithvi) detects current flood/water coverage from the latest available Sentinel imagery.
2. **Rainfall trend** — recent + short-term forecast precipitation per district (NASA GPM).
3. **Terrain susceptibility** — static per-district flood-proneness from elevation/drainage data (SRTM DEM), since flat, low-lying, near-river land floods faster than highland for the same rainfall.

These three signals are fused into a single risk score (Low / Moderate / High / Severe) per district, refreshed on a schedule, and shown on a map in a React Native app.

**Why this architecture, explicitly:** live on-demand inference from the phone was rejected — geospatial processing takes real time (fetching imagery, running the model, computing fusion), so a live request would mean the user staring at a spinner, and it would hammer the free-tier satellite/rainfall APIs on every app open. A scheduled backend job that pre-computes results and caches them is both the better UX and the standard pattern real disaster-monitoring systems use.

---

## 2. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Segmentation model | Prithvi-EO-1.0-100M (NASA/IBM), fine-tuned | Geospatial foundation model, pretrained on HLS (Harmonized Landsat-Sentinel) data — better sample efficiency than training a CNN from scratch |
| Training environment | Kaggle notebook (free GPU) | See companion notebook |
| Backend | Python, FastAPI | Matches your existing stack (jobsync, lifsync, AutoFix-Agent) |
| Scheduler | APScheduler (simplest) or Airflow DAG (if you want to reuse your MLOps stack from the politician classifier) | Daily job that refreshes risk scores |
| Database | SQLite for v1 (Postgres if you want it production-grade later) | Just caching computed scores + small metadata, not a heavy write load |
| Frontend | React Native (Expo recommended for speed) | Your explicit choice |
| Map rendering | `react-native-maps` | Standard, well-supported |
| Containerization | Docker + docker-compose | Matches your existing MLOps pattern |
| CI/CD | GitHub Actions | Matches your existing pattern |

---

## 3. Geographic Scope — v1 District List

Rather than "all of Pakistan" (most of the country has near-zero flood risk and would dilute the demo) or a single city (too narrow to be impressive), v1 targets the historically highest flood-risk districts along the Indus basin — the same belt hit hardest in the 2022 floods. This is a defensible, data-driven scoping decision you can explain in an interview.

**v1 district list** (Sindh + South Punjab, Indus basin):
Dadu, Jacobabad, Qambar Shahdadkot, Larkana, Shikarpur, Kashmore, Khairpur, Sukkur, Naushahro Feroze, Badin, Thatta/Sujawal, Dera Ghazi Khan, Rajanpur

Store this as a config file, not hardcoded — `config/districts.geojson` with each district's boundary polygon (from an open admin-boundaries source, e.g. Pakistan's district shapefiles via [GADM](https://gadm.org) or [HDX](https://data.humdata.org)), so adding more districts later is a config change, not a code change.

---

## 4. System Architecture

```
┌─────────────────────────┐
│   Kaggle (offline)      │
│   Train Prithvi on      │
│   Sen1Floods11          │
│   → export model.pt     │
└───────────┬─────────────┘
            │ (manual download, one-time + occasional retraining)
            ▼
┌─────────────────────────────────────────────────────────┐
│                    Backend (scheduled)                   │
│                                                           │
│  Daily job (APScheduler/Airflow):                        │
│   1. For each district: check Copernicus Data Space      │
│      Ecosystem for new Sentinel-1/2 imagery               │
│   2. If new imagery available → run Prithvi model         │
│      → water/flood extent mask                            │
│   3. Fetch NASA GPM rainfall (last 3/7 days) per district │
│   4. Look up static terrain susceptibility (precomputed)  │
│   5. Fuse into risk score → write to DB                   │
│                                                           │
│  FastAPI serving layer (always-on):                       │
│   - GET /districts → list + current risk levels           │
│   - GET /districts/{id} → detail (breakdown of 3 signals) │
│   - GET /districts/{id}/history → trend over time          │
└───────────┬───────────────────────────────────────────────┘
            │ REST/JSON
            ▼
┌─────────────────────────┐
│  React Native app        │
│  - Map, color-coded by   │
│    risk level             │
│  - Tap district → detail  │
└─────────────────────────┘
```

---

## 5. Component: Segmentation Model (see companion notebook)

Trained separately on Kaggle. Output artifacts needed by the backend:
- `flood_segmentation_model.pt` — fine-tuned weights
- `model_config.json` — input band order, normalization stats, input chip size (matches what the model was trained on, so inference-time preprocessing matches exactly)
- `metrics.json` — mIoU, F1, precision/recall (for your README/LinkedIn post, and to sanity-check the model isn't degrading over time)

**Important distinction Claude Code should preserve:** the model is trained on the *global* Sen1Floods11 benchmark (11 flood events worldwide, no Pakistan imagery in it). It is then *applied* to live Pakistan Sentinel imagery in production. This is standard transfer — the model learns general "what does water/flood look like from orbit" features, not Pakistan-specific patterns. State this explicitly in the README so it doesn't read as a data-leakage mistake.

---

## 6. Component: Data Ingestion & Risk Fusion Pipeline

### 6.1 Satellite ingestion
- Use Copernicus Data Space Ecosystem API (free registration at dataspace.copernicus.eu) to query for the latest Sentinel-2 L2A (or Sentinel-1 GRD if cloud cover blocks optical) scene covering each district's bounding box.
- Sentinel-2 revisit is ~5 days per exact location, so "daily" job just means "check daily, only process if something new arrived."
- Preprocess: clip to district boundary, resample/normalize to match the training pipeline's exact band order and normalization stats (from `model_config.json`).
- Run inference → binary water/flood mask → compute % of district area currently flagged as water.
- Compare against a precomputed **dry-season baseline** extent (compute once, from historical dry-month imagery) to get a **water anomaly score**, not raw % (raw % is misleading near rivers/lakes that are always "water").

### 6.2 Rainfall ingestion
- NASA GPM IMERG data via Earthdata/GES DISC (free registration) or Google Earth Engine (free for research use — likely the simpler path since it also gives easy spatial aggregation per district polygon without manual raster wrangling).
- Pull cumulative rainfall for the last 3 and 7 days per district.
- Compare against historical seasonal average for that district → **rainfall anomaly score**.

### 6.3 Terrain susceptibility (static, computed once)
- SRTM elevation data (via Google Earth Engine or USGS EarthExplorer, both free).
- Compute per-district: mean elevation, slope, distance-to-major-river.
- Combine into a static 0–1 **terrain susceptibility score** per district. This doesn't change day to day — compute once, store in `config/districts.geojson` as a property.

### 6.4 Fusion → risk score
Start with a **transparent, rule-based weighted fusion**, not a trained ML model — you don't have historical ground-truth "was this district actually flooded" labels at the volume needed to train a fusion model responsibly yet. Be upfront about this in the README; it's the honest and correct call, and "swap in a learned fusion model once historical outcome data is collected" is a legitimate stated v2, not a cut corner.

```
risk_score = w1 * water_anomaly + w2 * rainfall_anomaly + w3 * terrain_susceptibility
```
Normalize each term 0–1, start with equal weights (w1=w2=w3=0.33), map final score to:
- 0.0–0.25 → Low
- 0.25–0.5 → Moderate
- 0.5–0.75 → High
- 0.75–1.0 → Severe

Store the three sub-scores alongside the final score — the app should be able to show *why* a district is flagged (e.g., "High risk: heavy rainfall this week, terrain is flood-prone, satellite hasn't detected standing water yet" is a much better UI moment than just a red dot).

### 6.5 Scheduling
- `APScheduler` cron job, once daily, iterating the district list.
- Log each run (district, whether new imagery was found, risk score, timestamp) — this log is also your "history" data for the trend view.

---

## 7. Component: API Backend (FastAPI)

```
GET  /districts
     → [{ id, name, risk_level, risk_score, last_updated }]

GET  /districts/{id}
     → { id, name, risk_level, risk_score,
         signals: { water_anomaly, rainfall_anomaly, terrain_susceptibility },
         last_satellite_pass: <date>,
         geometry: <geojson polygon> }

GET  /districts/{id}/history?days=30
     → [{ date, risk_score }]
```

Database schema (SQLite, minimal):
- `districts` (id, name, geometry, terrain_susceptibility)
- `risk_snapshots` (district_id, timestamp, water_anomaly, rainfall_anomaly, risk_score, risk_level)

---

## 8. Component: React Native Frontend

- Scaffold with Expo.
- Screens:
  1. **Map screen** — `react-native-maps`, district polygons color-coded by risk level, fetched from `GET /districts`.
  2. **District detail screen** — tapped district shows current risk breakdown (the three signals) + a simple line chart of the last 30 days (`GET /districts/{id}/history`).
- Keep state management simple (React Query or plain `useEffect` + `fetch` is enough at this scale — no need for Redux).

---

## 9. MLOps / Deployment

Reuse the pattern from your politician classifier project:
- Dockerize the FastAPI backend + scheduled job.
- GitHub Actions: lint/test on PR, build+push Docker image on merge to main.
- Track model versions with a simple `models/` folder + `metrics.json` per version (MLflow if you want the fuller setup, but for a single model that doesn't retrain often, this may be overkill — your call).

---

## 10. Data Source Reference

| Data | Source | Access |
|---|---|---|
| Sentinel-1/2 imagery | Copernicus Data Space Ecosystem | Free registration, dataspace.copernicus.eu, documented Python API (OData/STAC/openEO) |
| Flood training dataset | Sen1Floods11 | Public, github.com/cloudtostreet/Sen1Floods11 (GCS bucket `gs://sen1floods11/`), also mirrored on Hugging Face Datasets |
| Pretrained backbone | Prithvi-EO-1.0-100M | Hugging Face: `ibm-nasa-geospatial/Prithvi-100M` |
| Rainfall | NASA GPM IMERG | Free via NASA Earthdata/GES DISC, or Google Earth Engine (free for research use) |
| Elevation/terrain | SRTM DEM | Free via Google Earth Engine or USGS EarthExplorer |
| District boundaries | GADM or HDX | Free shapefile/GeoJSON downloads |

---

## 11. Build Phases

**Phase 0** (done separately): train + export the segmentation model on Kaggle.

**Phase 1 — Backend core**
- District config + boundaries
- Satellite ingestion + inference pipeline for one district (prove it end-to-end before scaling to all 13)
- Rainfall ingestion
- Terrain susceptibility (one-time computation)
- Fusion logic
- SQLite storage

**Phase 2 — API**
- FastAPI endpoints on top of Phase 1's data
- Scheduler wired in for all districts

**Phase 3 — Frontend**
- React Native map screen against live API
- District detail screen + history chart

**Phase 4 — Polish for demo**
- Seed a few days of history so the trend chart isn't empty on day one
- README with architecture diagram, sample screenshots, model metrics
- Short screen-recording for LinkedIn

---

## 12. Success Criteria

- Model: mIoU on Sen1Floods11 test split in the same range as published benchmarks (sanity check, not a target to beat).
- Pipeline: successfully processes all 13 districts on a real scheduled run without manual intervention.
- App: opens to a map with real, current risk levels — not placeholder data.
- Honesty check for the README: state clearly that risk fusion is rule-based (not ML-trained) in v1, and why — this is a strength to state plainly, not a weakness to hide.
