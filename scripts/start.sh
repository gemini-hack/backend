#!/bin/bash
set -e

echo "🚀 Applying database migrations..."
alembic upgrade head

echo "🌱 Running seed script..."
python scripts/seed_hackathon_data.py

echo "🔥 Starting application..."
exec uvicorn main:app --host 0.0.0.0 --port 8000 --reload
