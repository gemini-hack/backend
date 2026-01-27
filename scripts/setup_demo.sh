#!/bin/bash
set -e

echo "🚀 Starting MIRA Hackathon Demo Setup..."

# 1. Run Migrations (Safe to run multiple times)
echo "📦 Applying Database Migrations..."
alembic upgrade head

# 2. Seed Data
echo "🌱 Seeding Demo Data..."
python scripts/seed_hackathon_data.py

echo "✅ Setup Complete!"
echo "------------------------------------------------"
echo "To start the backend, run: uvicorn app.main:app --reload"
echo "To trigger agents, POST to: http://localhost:8000/api/v1/agents/trigger-rounds"
echo "------------------------------------------------"
