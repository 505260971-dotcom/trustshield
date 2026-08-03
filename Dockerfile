# syntax=docker/dockerfile:1

# Build the React single-page application once, then have FastAPI serve the
# immutable files.  Production therefore needs only one exposed HTTP port.
FROM node:22-bookworm-slim AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CONTRACTGUARD_DATA_DIR=/data

# Tesseract is optional at the product level, but shipping it here means the
# documented scanned-PDF/image upload path works out of the box.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser backend/ /app/backend/
COPY --from=frontend-build --chown=appuser:appuser /src/frontend/dist /app/frontend/dist
RUN mkdir -p /data && chown appuser:appuser /data

USER appuser
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
