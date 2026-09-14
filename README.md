# Pakistan Flood Risk Monitor

A district-level flood risk monitor for Pakistan's Indus-basin flood belt —
14 Sindh/South-Punjab districts, the same belt hit hardest in the 2022
floods — fusing satellite water detection, rainfall anomaly, terrain
susceptibility, soil moisture, and river discharge into one risk score per
district, shown on a map.

Full spec: [`files/IMPLEMENTATION_PLAN.md`](files/IMPLEMENTATION_PLAN.md).
Model training notebook: [`files/flood_segmentation_training.ipynb`](files/flood_segmentation_training.ipynb).

This README covers what's actually built, what's real vs. mocked, and the
judgment calls made while implementing the plan — limitations are stated
plainly rather than hidden.

## What's here

```
backend/    FastAPI service + APScheduler daily job (Phases 1-2 of the plan)
frontend/   Expo/React Native app — map + district detail screens (Phase 3)
config/     districts.geojson (real boundaries + terrain scores), settings.example.env
scripts/    one-time/maintenance scripts (district boundaries, terrain, river proximity + discharge calibration, history backfill)
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
project doesn't ship with — not because the named source is wrong.

| Signal | Plan suggested | Actually used | Why | Status |
|---|---|---|---|---|
| District boundaries | GADM or HDX | **HDX** `cod-ab-pak` (OCHA, 2024) | GADM's Pakistan layer is a 2022 snapshot with pre-2005/2013 district lines — no separate Qambar Shahdadkot or Sujawal. HDX has all 160 current districts. | ✅ Live, real |
| Terrain / elevation | Google Earth Engine or USGS EarthExplorer | **opentopodata.org** (public SRTM API, no signup) | GEE needs a GCP project + service account. Same underlying SRTM data, sampled via a free public endpoint instead. | ✅ Live, real (see limitation below) |
| Rainfall | NASA GPM IMERG / GEE | **Open-Meteo** (archive API, no signup) | GPM/GEE both need a registered account. Open-Meteo serves real reanalysis precipitation, current through today, with zero setup. | ✅ Live, real by default |
| Satellite water extent | Copernicus Data Space Ecosystem + fine-tuned Prithvi | **Mock provider** by default; a full Copernicus NDWI + Sentinel-1 SAR pipeline is implemented and confirmed working end-to-end | CDSE needs a registered account with two separate credential types (see below), and the trained model doesn't exist until you run the Kaggle notebook. | ✅ Real path confirmed working; ⚠️ mocked by default (your own credentials needed) |
| Soil moisture *(not in the original plan)* | — | **Open-Meteo** (`soil_moisture_0_to_10cm_mean`, no signup) | Antecedent moisture — how saturated the ground already is — matters for flood risk independent of this week's rainfall (the SCS curve-number concept). Open-Meteo serves it directly. | ✅ Live, real |
| River discharge *(not in the original plan)* | — | **Open-Meteo Flood API** (GloFAS-modeled `river_discharge`, no signup) | The most direct, dynamic flood indicator in the system — actual modeled water flow in the channel, not a proxy. Needed a one-time per-district calibration step first, since a naive nearest-river query point reads 0 m³/s even on the Indus at Sukkur — see `scripts/calibrate_discharge_points.py`. | ✅ Live, real |

### District count: 14, not 13

The plan lists "Thatta/Sujawal" as one entry (13 districts). Sujawal was
split out of Thatta as its own district in 2013 and HDX's current data
treats them separately — this project kept them separate rather than
merging two real polygons back into one, so the actual district count is
14. See `scripts/build_districts_config.py` for the full reasoning.

### Terrain susceptibility — elevation, relief, and river distance

`scripts/compute_terrain_susceptibility.py` computes a score from SRTM
elevation + local relief (sampled via opentopodata). That alone missed
something real: Dera Ghazi Khan (highest mean elevation/relief in the set)
scored lowest — 0.000, implying almost no flood risk — despite real
historical flash-flood risk from hill torrents descending onto its plains,
a mechanism elevation alone doesn't capture.

`scripts/compute_river_proximity.py` closes that gap: HydroRIVERS
(HydroSHEDS, free, no signup) gives the actual distance from each district
to the nearest major river (discharge ≥ 500 m³/s), blended in as 35% of
the final terrain susceptibility. Worth noting plainly: **12 of the 14
districts already sit directly on (0.0 km from) a major river** — expected,
since the district list was selected because these districts sit in the
Indus floodplain. The term still fixed the case that mattered most — Dera
Ghazi Khan's score moved from 0.000 to 0.350, correctly reflecting that it
sits on a major river despite its higher elevation, and Rajanpur moved
similarly (0.309 → 0.551). Full district-by-district numbers and the
distance-to-score decay function are in the script itself.

Run order matters: `build_districts_config.py` → `compute_terrain_susceptibility.py`
→ `compute_river_proximity.py` → `calibrate_discharge_points.py`. The two
middle scripts need `shapely`/`pyshp`, intentionally *not* in
`backend/requirements.txt` — see `scripts/requirements.txt`, a separate
isolated environment for one-time scripts the deployed API never needs.

### Satellite signal — what "mock by default" actually means

`app/ingestion/satellite_mock.py` returns a synthetic water-anomaly value,
deterministic per (district, date) and loosely correlated with terrain +
that day's real rainfall anomaly so demo/history data tells a coherent
story. **Every API response and DB row tags which signals are real**
(`water_source`, `rainfall_source` fields) — the app never presents
synthetic data as a live satellite observation.

The real path (`app/ingestion/satellite_copernicus.py`) implements CDSE
OAuth2, Sentinel-2 product search, S3 band download, and NDWI water
detection (McFeeters 1996 — a well-established remote-sensing method that
works even without the trained model). It needs **two separate CDSE
credential types**, a distinction not obvious from CDSE's own docs:

1. Register a free account at [dataspace.copernicus.eu](https://dataspace.copernicus.eu).
2. **OData search credentials** — create a Sentinel Hub OAuth client
   (Client Credentials flow) at the
   [Sentinel Hub dashboard](https://shapps.dataspace.copernicus.eu/dashboard/#/account/settings)
   → User settings → OAuth clients → Create. Add as `CDSE_CLIENT_ID` /
   `CDSE_CLIENT_SECRET` in `.env`.
3. **Band download credentials** — a *different* credential type. The
   Sentinel Hub OAuth token from step 2 authenticates OData search but
   can't download product bytes (CDSE rejects it with `401
   "Token audience not allowed"`). Product downloads go through CDSE's
   S3-compatible object storage instead — also the officially recommended
   method for full-dataset downloads, and more efficient here since it
   fetches only the needed band files instead of the ~1.1GB SAFE archive.
   Generate keys at the
   [S3 keys manager](https://eodata-s3keysmanager.dataspace.copernicus.eu/)
   → Add Credential. Add as `CDSE_S3_ACCESS_KEY` / `CDSE_S3_SECRET_KEY`.
4. Set `SATELLITE_PROVIDER=copernicus`.

See `config/settings.example.env` for the full annotated list, and the
`satellite_copernicus.py` module docstring for implementation notes — this
is the part of the backend most exposed to an upstream API changing shape.
Its NDWI math is unit-tested (`backend/tests/test_ndwi.py`); the network/S3
path is exercised against the live API rather than only unit-tested, since
no CI environment here holds real credentials.

**Sentinel-1 SAR fallback.** Sentinel-2 is optical — during Pakistan's
monsoon (the actual flood season), cloud cover averages 90%+, and optical
water-detection misses roughly a quarter of real surface water in those
months ([Radar vs optical, PLOS One](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0314033)).
A comparable open-source Pakistan flood-risk project
([GEE-Pakistan-Flood-Risk-Model](https://github.com/Rohmashakoor/GEE-Pakistan-Flood-Risk-Model))
hit the same problem mapping the 2022 floods and switched to Sentinel-1 SAR,
which sees through cloud cover. `CopernicusSatelliteProvider` does the same
automatically: if no usable Sentinel-2 scene exists, it falls back to
`app/ingestion/satellite_sentinel1.py` using the same CDSE credentials, no
extra signup. Bands are read as a windowed crop straight from CDSE's S3
storage via a GCP-based reprojection (Sentinel-1 GRD products aren't
map-projected out of the box), rather than downloading the full ~815MB
scene. When a scene only partially covers a district's bounding box the
provider tries the next candidate scene instead of returning a result
computed mostly from padding.

Water/non-water classification uses Otsu's method (1979, standard automatic
bimodal thresholding) on a log-scaled transform of the raw backscatter —
**not** radiometrically-calibrated sigma0, a documented simplification in
the same spirit as the NDWI threshold and the terrain heuristic elsewhere
in this project. One consequence worth knowing: flooded or irrigated rice
paddies return low backscatter too, the same as open water, so a raw water
fraction in a district with significant paddy agriculture should be read
as "low-backscatter fraction" rather than proven flood extent.

## Segmentation model

Trained separately on Kaggle: [`files/flood_segmentation_training.ipynb`](files/flood_segmentation_training.ipynb)
(the notebook has that run's actual outputs baked in as a record). It
fine-tunes Prithvi-EO-1.0-100M on Sen1Floods11 (a global benchmark, no
Pakistan imagery — applying it to live Pakistan Sentinel scenes is standard
transfer, not data leakage) alongside a U-Net baseline for comparison, and
picks whichever scores higher automatically. Its three output files are
already in `models/` (see `models/README.md`) — the backend loads them at
startup; `GET /health` confirms `segmentation_model_loaded: true`.

**Metrics** (`models/metrics.json`, full run — 431 hand-labeled chips, the
paper's own 252/89/90 train/val/test split; U-Net 25 epochs, Prithvi 50
epochs with a cosine LR schedule; test metrics from tiled full-resolution
inference, not a single downsampled crop):

| Model | mean IoU | water IoU | F1 (water) | Precision | Recall |
|---|---|---|---|---|---|
| **U-Net (resnet34)** — selected | **0.890** | 0.811 | 0.895 | 0.889 | 0.902 |
| Prithvi-EO-1.0 fine-tune | 0.856 | 0.752 | 0.858 | 0.852 | 0.865 |

The U-Net baseline won. An independent, peer-reviewed reproduction of this
exact benchmark ([SIGSPATIAL 2023](https://arxiv.org/abs/2309.14500)) found
the same thing — U-Net beating Prithvi in-distribution on Sen1Floods11 — so
this is a documented pattern on this dataset, not a pipeline bug.

Getting to these numbers took a few iterations. The first working run (25
epochs, resizing each 512×512 chip down to 224×224) scored U-Net 0.874 /
Prithvi 0.822 mIoU — Prithvi sitting well behind IBM's own published
benchmark for this exact model on this exact dataset (mIoU 0.887, water IoU
0.805). Correcting the learning rate/schedule/epochs/batch size and
replacing the decoder with a real multi-scale FPN+PPM (UperNet-style)
architecture each came back statistically flat, ruling out "undertrained"
and "decoder too simple" as the cause. What actually moved both models'
numbers was switching from resizing the whole chip to training on
native-resolution random crops and evaluating with tiled (sliding-window)
inference over the full test image. Full diagnostic trail is in the
notebook's section 0.

`models/sample_predictions.png` shows both models tracking real water body
shapes (rivers, scattered ponds, a large flood extent), not degenerate
all-one-class output.

## Risk fusion — rule-based by design, not a cut corner

```
risk_score = 0.25 * water_anomaly + 0.20 * rainfall_anomaly + 0.15 * terrain_susceptibility
           + 0.15 * soil_moisture_anomaly + 0.25 * river_discharge_anomaly
```

`0.0–0.25` Low · `0.25–0.5` Moderate · `0.5–0.75` High · `0.75–1.0` Severe.

Deliberately not a trained model (plan section 6.4): there's no volume of
historical "was this district actually flooded" ground truth to train a
fusion model on responsibly yet. Every score is explainable from its five
sub-scores — see `backend/app/fusion/risk.py` and the detail screen's "why
this score" breakdown. Soil moisture and river discharge were added after
looking at comparable open-source flood-risk projects turned up two more
real, no-signup data sources. Weights are rebalanced from an earlier
equal-ish three-way split; still a documented heuristic, not fitted to any
outcome data — river discharge and satellite water get the top weight as
the two most direct flood indicators, terrain and soil moisture the lowest
as the slower-changing, more baseline-like factors.

## Testing

```bash
cd backend && pytest -v      # fusion logic, all ingestion providers (network mocked), NDWI/SAR math, alerting, full API flow
cd frontend && npx tsc --noEmit && npx expo lint   # type-check + lint
```

CI (`.github/workflows/ci.yml`) runs the backend suite on every PR and
builds (and, on merge to `main`, pushes to GHCR) the Docker image.

## Architecture

```
Kaggle (offline)                    Free, no-signup, real data              Needs your own account
┌──────────────────┐               ┌─────────────────────────┐            ┌──────────────────────┐
│ Train Prithvi/    │               │ HDX district boundaries │            │ Copernicus Data Space │
│ U-Net on          │               │ Open-Meteo rainfall,    │            │ (satellite imagery)   │
│ Sen1Floods11       │               │ soil moisture, GloFAS   │            └───────────┬───────────┘
│ -> model.pt        │               │ opentopodata SRTM       │                        │
└─────────┬──────────┘               └────────────┬────────────┘                        │
          │ copy into models/                     │                                      │
          │                                        ▼                                      ▼
          │                          ┌─────────────────────────────────────────────────────┐
          └─────────────────────────▶│         Backend (FastAPI + APScheduler)              │
                                     │  Daily job: 5 signals -> rule-based fusion -> SQLite  │
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
- **Phase 1** (backend core): ✅ done — real district config, five real signal providers, fusion, SQLite.
- **Phase 2** (API): ✅ done — all endpoints + manual refresh trigger + scheduler.
- **Phase 3** (frontend): ✅ done — web is the primary target, with a real interactive Leaflet map (district polygons, click-through, zoom/pan) and a detail screen with signal breakdown + trend chart. Native (iOS/Android via react-native-maps) still builds but hasn't been run on a device or emulator.
- **Phase 4** (polish): mostly done — `scripts/seed_history.py` backfills real historical rainfall, model metrics table is in this README, push alerting via ntfy.sh is wired in.

## Honesty checklist (plan section 12)

- ✅ Risk fusion is rule-based, stated plainly, not hidden behind ML framing.
- ✅ Every risk snapshot tags which signals are real vs. mocked (`water_source`, `rainfall_source`, etc.).
- ✅ Data-source substitutions (table above) are documented with the actual reason, not silently swapped.
- ✅ The terrain score's known simplification (point-sampled elevation/relief + straight-line river distance, not a full hydrological flow-path model) is named, not hidden.
- ✅ "App opens to a map with real, current risk levels for all signals" — true once you add your own CDSE credentials (two separate types — see the satellite section above); confirmed with a full end-to-end refresh across all 14 districts, real Sentinel-2/Sentinel-1 water detection, rainfall, soil moisture, and GloFAS discharge all in one pass. Water anomaly stays synthetic without CDSE credentials.
- ⚠️ A full 14-district refresh with `SATELLITE_PROVIDER=copernicus` is slow (real satellite band downloads add real time — `POST /districts/refresh` covers all 14 districts in one call, there's no per-district endpoint) and can trip Open-Meteo's rate limiter under sustained sequential load. Individual signals fall back to neutral rather than failing the whole refresh when that happens — not a crash, but a real degradation worth knowing about before relying on every field from a single run. Not yet fixed with backoff/spacing between districts. The mock satellite provider skips the slow part entirely.
- ✅ Push alerting (ntfy.sh) fires once when a district first reaches Severe, not on every refresh it stays there — off by default, see `config/settings.example.env`.
