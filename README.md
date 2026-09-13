# Pakistan Flood Risk Monitor

A district-level flood risk monitor for Pakistan's Indus-basin flood belt —
14 Sindh/South-Punjab districts, the same belt hit hardest in the 2022
floods — fusing satellite water detection, rainfall anomaly, and static
terrain susceptibility into one risk score per district, shown on a map.

Full spec: [`files/IMPLEMENTATION_PLAN.md`](files/IMPLEMENTATION_PLAN.md).
Model training notebook: [`files/flood_segmentation_training.ipynb`](files/flood_segmentation_training.ipynb).

This README covers what's actually built, what's real vs. mocked right
now, and the judgment calls made while implementing the plan — in the same
spirit as the plan's own honesty principle (section 12): state limitations
plainly rather than hide them.

## What's here

```
backend/    FastAPI service + APScheduler daily job (Phases 1-2 of the plan)
frontend/   Expo/React Native app — map + district detail screens (Phase 3)
config/     districts.geojson (real boundaries + terrain scores), settings.example.env
scripts/    one-time/maintenance scripts (district boundaries, terrain, history backfill)
models/     where the Kaggle notebook's trained weights go (not checked in)
files/      the original planning doc + training notebook
```

## Quickstart

```bash
# 1. Backend (isolated venv — never installs into your system Python)
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
# -> syncs config/districts.geojson into SQLite, starts the API + scheduler

# 2. Get real risk data without waiting for the 02:00 UTC scheduled run
curl -X POST http://localhost:8000/districts/refresh

# 3. (optional) backfill history so the trend chart isn't empty
python ../scripts/seed_history.py --days 30

# 4. Frontend
cd ../frontend
npm install
npx expo start
```

`GET http://localhost:8000/health` reports which providers are active. With
zero configuration, the app runs end-to-end today: real district
boundaries, real rainfall, a real (if simple) terrain score, and a clearly
labeled synthetic satellite signal — see below for exactly what that means
and how to make it fully live.

## Data sourcing decisions

The plan named specific sources (NASA GPM, Google Earth Engine, GADM) as
options, and explicitly invited substituting equivalents. Every substitution
below was made because the named source needs a registered account this
environment doesn't have — not because the named source is wrong.

| Signal | Plan suggested | Actually used | Why | Status |
|---|---|---|---|---|
| District boundaries | GADM or HDX | **HDX** `cod-ab-pak` (OCHA, 2024) | GADM's Pakistan layer (checked at build time) is a 2022 snapshot with pre-2005/2013 district lines — no separate Qambar Shahdadkot or Sujawal. HDX has all 160 current districts. | ✅ Live, real |
| Terrain / elevation | Google Earth Engine or USGS EarthExplorer | **opentopodata.org** (public SRTM API, no signup) | GEE needs a GCP project + service account; this needed real elevation numbers today. Same underlying SRTM data, sampled via a free public endpoint instead. | ✅ Live, real (see limitation below) |
| Rainfall | NASA GPM IMERG / GEE | **Open-Meteo** (archive API, no signup) | GPM/GEE both need a registered account. Open-Meteo serves real reanalysis precipitation, current through today, with zero setup. | ✅ Live, real by default |
| Satellite water extent | Copernicus Data Space Ecosystem + fine-tuned Prithvi | **Mock provider** by default; a full Copernicus + NDWI (+ trained model) pipeline is implemented but needs your own free CDSE account | CDSE needs a registered account this project can't create for you, and the trained model doesn't exist until you run the Kaggle notebook. | ⚠️ Mocked by default, real path implemented |

### District count: 14, not 13

The plan lists "Thatta/Sujawal" as one entry (13 districts). Sujawal was
split out of Thatta as its own district in 2013 and HDX's current data
treats them separately — this project kept them separate rather than
merging two real polygons back into one, so the actual district count is
14. See `scripts/build_districts_config.py` for the full reasoning.

### Terrain susceptibility — known limitation

`scripts/compute_terrain_susceptibility.py` computes a real score from SRTM
elevation + local relief (sampled via opentopodata), normalized across the
14 districts. It does **not** include distance-to-major-river, which the
plan calls out as useful (needs a hydrology layer like HydroRIVERS, out of
scope for a point-sampled API). One consequence worth naming: Dera Ghazi
Khan scores lowest in this v1 (highest mean elevation/relief in the set),
even though it has real historical flash-flood risk from hill torrents
descending onto its plains — a mechanism this elevation-only heuristic
doesn't capture. Adding a river-distance term is a clearly labeled v1.1
TODO, not a silently accepted gap.

### Satellite signal — what "mock by default" actually means

`app/ingestion/satellite_mock.py` returns a synthetic water-anomaly value,
deterministic per (district, date) and loosely correlated with terrain +
that day's real rainfall anomaly so demo/history data tells a coherent
story. **Every API response and DB row tags which signals are real**
(`water_source`, `rainfall_source` fields) — the app never presents
synthetic data as a live satellite observation.

The real path (`app/ingestion/satellite_copernicus.py`) is fully
implemented: CDSE OAuth2, Sentinel-2 product search, band download, and
NDWI water detection (McFeeters 1996 — a real, well-established
remote-sensing method that works even without the trained model). To turn
it on:
1. Register a free account at [dataspace.copernicus.eu](https://dataspace.copernicus.eu).
2. Add `CDSE_CLIENT_ID` / `CDSE_CLIENT_SECRET` to `.env` (see `config/settings.example.env`).
3. Set `SATELLITE_PROVIDER=copernicus`.

That module's network calls need live credentials this environment doesn't
have, so — like the training notebook's own callout about checking the
Prithvi model card before running — treat a first live run as a smoke test,
not something already proven end-to-end here. Its NDWI math (the actual
water-detection logic) is unit-tested (`backend/tests/test_ndwi.py`).

## Segmentation model

Trained separately on Kaggle: [`files/flood_segmentation_training.ipynb`](files/flood_segmentation_training.ipynb)
(the notebook now has that run's actual outputs baked in, as a record).
It fine-tunes Prithvi-EO-1.0-100M on Sen1Floods11 (global benchmark, no
Pakistan imagery — applying it to live Pakistan Sentinel scenes later is
standard transfer, not data leakage) alongside a U-Net baseline for
comparison, and picks whichever scores higher automatically. Its three
output files are already in `models/` (see `models/README.md`) — the
backend loads them at startup; `GET /health` confirms
`segmentation_model_loaded: true`.

**Metrics** (`models/metrics.json`, full run — 431 hand-labeled chips, the
paper's own 252/89/90 train/val/test split; U-Net 25 epochs, Prithvi 50
epochs with a cosine LR schedule; test metrics from tiled full-resolution
inference, not a single downsampled crop — see the notebook's changelog):

| Model | mean IoU | water IoU | F1 (water) | Precision | Recall |
|---|---|---|---|---|---|
| **U-Net (resnet34)** — selected | **0.890** | 0.811 | 0.895 | 0.889 | 0.902 |
| Prithvi-EO-1.0 fine-tune | 0.856 | 0.752 | 0.858 | 0.852 | 0.865 |

The U-Net baseline won, and this is the smaller of two real findings here.
An independent, peer-reviewed reproduction of this exact benchmark
([SIGSPATIAL 2023](https://arxiv.org/abs/2309.14500)) found the same thing —
U-Net beating Prithvi in-distribution on Sen1Floods11 — so this is a
documented pattern on this dataset, not a bug in this pipeline.

The more interesting finding is what it took to get these numbers. The
first working run (25 epochs, resizing each 512x512 chip down to 224x224)
scored U-Net 0.874 / Prithvi 0.822 mIoU — Prithvi sitting ~11 points of
water IoU behind IBM's own published benchmark for this exact model on this
exact dataset (mIoU 0.887, water IoU 0.805). Three rounds of diagnosis
before this one — correcting the learning rate/schedule/epochs/batch size
against NASA-IMPACT's actual training config, then replacing the decoder
with a real multi-scale FPN+PPM (UperNet-style) architecture — each came
back statistically flat, which is itself useful evidence: it ruled out
"undertrained" and "decoder too simple" as the cause. What actually moved
both models' numbers was switching from resizing the whole chip to
training on native-resolution random crops and evaluating with tiled
(sliding-window) inference over the full test image — the independent
reproduction's config specified exactly that, and this pipeline didn't
until this pass. Full diagnostic trail, with what was tried and ruled out
at each step, is in the notebook's section 0.

`models/sample_predictions.png` shows both models tracking real water body
shapes (rivers, scattered ponds, a large flood extent) — not degenerate
all-one-class output; the river-tracing detail visibly sharpened once
training moved to native-resolution crops.

## Risk fusion — rule-based by design, not a cut corner

```
risk_score = 0.34 * water_anomaly + 0.33 * rainfall_anomaly + 0.33 * terrain_susceptibility
```

`0.0–0.25` Low · `0.25–0.5` Moderate · `0.5–0.75` High · `0.75–1.0` Severe.

Deliberately not a trained model (plan section 6.4): there's no volume of
historical "was this district actually flooded" ground truth to train a
fusion model on responsibly yet. Every score is explainable from its three
sub-scores — see `backend/app/fusion/risk.py` and the detail screen's
"why this score" breakdown.

## Testing

```bash
cd backend && pytest -v      # 22 tests: fusion logic, rainfall provider (network mocked), NDWI math, full API flow
cd frontend && npx tsc --noEmit && npx expo lint   # type-check + lint
```

CI (`.github/workflows/ci.yml`) runs the backend suite on every PR and
builds (and, on merge to `main`, pushes to GHCR) the Docker image.

## Architecture

```
Kaggle (offline)                    Free, no-signup, real data              Needs your own account
┌──────────────────┐               ┌─────────────────────────┐            ┌──────────────────────┐
│ Train Prithvi/    │               │ HDX district boundaries │            │ Copernicus Data Space │
│ U-Net on          │               │ Open-Meteo rainfall     │            │ (satellite imagery)   │
│ Sen1Floods11       │               │ opentopodata SRTM       │            └───────────┬───────────┘
│ -> model.pt        │               └────────────┬────────────┘                        │
└─────────┬──────────┘                            │                                      │
          │ copy into models/                     ▼                                      ▼
          │                          ┌─────────────────────────────────────────────────────┐
          └─────────────────────────▶│         Backend (FastAPI + APScheduler)              │
                                     │  Daily job: rainfall + water anomaly + terrain        │
                                     │  -> rule-based fusion -> SQLite                        │
                                     │  GET /districts, /districts/{id}, /districts/{id}/history │
                                     └───────────────────────┬─────────────────────────────┘
                                                              │ REST/JSON
                                                              ▼
                                     ┌─────────────────────────────────────────────────────┐
                                     │  React Native app (Expo) — map + district detail      │
                                     └─────────────────────────────────────────────────────┘
```

## Status against the plan's phases

- **Phase 0** (train model): ✅ done — trained on Kaggle, weights + metrics in `models/`, backend confirmed loading them.
- **Phase 1** (backend core): ✅ done — real district config, real rainfall + terrain, mock/real-ready satellite, fusion, SQLite.
- **Phase 2** (API): ✅ done — all 3 endpoints + manual refresh trigger + scheduler.
- **Phase 3** (frontend): ✅ done — map screen (native) / ranked list (web fallback), detail screen with signal breakdown + trend chart.
- **Phase 4** (polish): partially done — `scripts/seed_history.py` backfills real historical rainfall, model metrics table is in this README; screenshots/LinkedIn recording of the running app are still to do.

## Honesty checklist (plan section 12)

- ✅ Risk fusion is rule-based, stated plainly, not hidden behind ML framing.
- ✅ Every risk snapshot tags which signals are real vs. mocked (`water_source`, `rainfall_source`).
- ✅ Data-source substitutions (table above) are documented with the actual reason, not silently swapped.
- ✅ The terrain score's known gap (no river-distance term) is named, not hidden.
- ⚠️ Not yet true: "app opens to a map with real, current risk levels for all signals" — water anomaly is synthetic until you add CDSE credentials and/or the trained model. Rainfall and terrain are real today.
