# models/

This directory is where the backend looks for the segmentation model
trained in `files/flood_segmentation_training.ipynb` (see
`backend/app/config.py`):

```
models/
  flood_segmentation_model.pt
  model_config.json
  metrics.json
```

None of these are checked into git (see `.gitignore`) — they're produced by
running the notebook on Kaggle and downloading its outputs.

**Status: filled in.** These are real weights from an actual Kaggle run (see
`files/flood_segmentation_training.ipynb`, which now has that run's outputs
baked in as a record). Both models trained the full 25 epochs with no
errors; the U-Net baseline won (mean IoU 0.874 vs. Prithvi's 0.822 — see
`metrics.json` for the full breakdown of both, and `sample_predictions.png`
for a visual check). `GET /health` reports `segmentation_model_loaded: true`
against these files, verified.

If you retrain and drop in new files, the section below still describes
what happens when this directory is empty:
- `app/inference/model.py` reports `available=False`.
- The live satellite provider (`app/ingestion/satellite_copernicus.py`)
  falls back to plain NDWI water thresholding, a real (if simpler)
  remote-sensing method that doesn't need the trained model.
- The default `satellite_provider=mock` setting doesn't touch this
  directory at all.

Steps to go from "notebook trained" to "backend using it":
1. Run `files/flood_segmentation_training.ipynb` on Kaggle (GPU enabled).
2. Download `flood_segmentation_model.pt`, `model_config.json`,
   `metrics.json` from Kaggle's output panel.
3. Copy them into this directory.
4. Set `SATELLITE_PROVIDER=copernicus` in `.env` and add your CDSE
   credentials (see `config/settings.example.env`) to actually fetch live
   Sentinel imagery for the model to run on — otherwise the weights sit
   here unused by the mock provider.
5. Restart the backend; `GET /health` will report
   `"segmentation_model_loaded": true`.

If you fine-tuned the Prithvi backbone instead of (or in addition to) the
U-Net baseline and it's the one you want in production, see the note at the
top of `backend/app/inference/model.py` — the loader currently only builds
the U-Net architecture and will log a clear warning rather than silently
mis-loading a ViT checkpoint into the wrong model shape.
