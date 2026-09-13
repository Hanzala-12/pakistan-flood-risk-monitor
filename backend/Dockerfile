FROM python:3.11-slim

# rasterio/GDAL need these system libs even with prebuilt wheels in some base images;
# kept minimal since the manylinux wheels bundle most of GDAL already.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY config ./config
# models/ is mounted as a volume in docker-compose.yml rather than baked into
# the image — weights come from your own Kaggle run, not from this repo.

ENV PYTHONPATH=/app
ENV DATABASE_URL=sqlite:////data/flood_risk.db
ENV DISTRICTS_GEOJSON_PATH=/app/config/districts.geojson

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
