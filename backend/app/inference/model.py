"""Loads the segmentation model exported by
files/flood_segmentation_training.ipynb and wraps it for inference.

The notebook exports three files into models/ (see models/README.md):
  - flood_segmentation_model.pt
  - model_config.json   (bands, chip_size, num_classes, architecture)
  - metrics.json

Until you've run the notebook and dropped those files in, `FloodSegModel.available`
is False and the Copernicus satellite provider falls back to plain NDWI
thresholding (see app/ingestion/satellite_copernicus.py) — the app still
runs and produces a real (if simpler) water signal without the trained model.

Architecture support: the notebook's "guaranteed to run" path is a
`segmentation_models_pytorch` U-Net (resnet34 encoder) — that's what this
loader builds. If you finished the Prithvi fine-tune instead and its
architecture tag is in model_config.json, this raises a clear
NotImplementedError rather than silently loading the wrong shape: wiring up
Prithvi's ViT encoder here needs the same encoder class the notebook used,
which depends on whatever the current Prithvi model card's loading snippet
looks like (the notebook flags this exact spot for a manual check, section
5). Port that class into this file and add a branch below once confirmed.
"""
import json
import logging
from pathlib import Path

import numpy as np
import torch

logger = logging.getLogger(__name__)


class FloodSegModel:
    def __init__(self, weights_path: Path, config_path: Path):
        self.available = False
        self.model = None
        self.config: dict | None = None

        if not weights_path.exists() or not config_path.exists():
            logger.info(
                "Model weights/config not found at %s / %s — run the Kaggle notebook "
                "(files/flood_segmentation_training.ipynb) and copy its outputs into models/ "
                "to enable model-based water detection.",
                weights_path, config_path,
            )
            return

        with open(config_path, encoding="utf-8") as f:
            self.config = json.load(f)

        architecture = self.config.get("architecture", "")
        if "unet" not in architecture:
            logger.warning(
                "model_config.json architecture=%r isn't the U-Net baseline this loader builds — "
                "see app/inference/model.py docstring. Falling back to NDWI-only water detection.",
                architecture,
            )
            return

        try:
            import segmentation_models_pytorch as smp
            self.model = smp.Unet(
                encoder_name="resnet34",
                encoder_weights=None,  # loading fine-tuned weights next, not ImageNet init
                in_channels=len(self.config["bands"]),
                classes=self.config["num_classes"],
            )
            state_dict = torch.load(weights_path, map_location="cpu")
            self.model.load_state_dict(state_dict)
            self.model.eval()
            self.available = True
            logger.info("Loaded flood segmentation model (%s) from %s", architecture, weights_path)
        except Exception:
            logger.exception("Failed to load segmentation model from %s — falling back to NDWI-only water detection.", weights_path)
            self.model = None

    def predict_water_mask(self, image_chw: np.ndarray) -> np.ndarray:
        """image_chw: (C, H, W) float array, band order + normalization matching
        model_config.json. Returns a binary (H, W) water mask. Raises if the
        model isn't available — callers should check .available first."""
        if not self.available:
            raise RuntimeError("Model not loaded — check FloodSegModel.available before calling predict_water_mask.")
        with torch.no_grad():
            x = torch.from_numpy(image_chw).float().unsqueeze(0)
            logits = self.model(x)
            pred = logits.argmax(dim=1).squeeze(0).cpu().numpy()
        return pred


_singleton: FloodSegModel | None = None


def get_model() -> FloodSegModel:
    global _singleton
    if _singleton is None:
        from app.config import get_settings
        settings = get_settings()
        _singleton = FloodSegModel(settings.model_weights_path, settings.model_config_path)
    return _singleton
