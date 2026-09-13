from fastapi import APIRouter

from app.config import get_settings
from app.inference.model import get_model

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    settings = get_settings()
    model = get_model()
    return {
        "status": "ok",
        "satellite_provider": settings.satellite_provider,
        "rainfall_provider": settings.rainfall_provider,
        "segmentation_model_loaded": model.available,
    }
