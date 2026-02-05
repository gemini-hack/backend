#!/bin/bash

# --- CONFIGURATION ---
SERVER_USER="idyvalour"
SERVER_IP="100.116.143.108"
REMOTE_DIR="/home/idyvalour/backend/"
SERVICE_NAME="app"

echo "🚀 Starting deployment to $SERVER_IP..."

# 1. Sync files from PC to Server
# We exclude things that make the transfer slow or break the server config
rsync -avz --progress \
    --exclude '__pycache__/' \
    --exclude '.venv/' \
    --exclude '.git/' \
    --exclude 'compose.override.yml' \
    ./ "$SERVER_USER@$SERVER_IP:$REMOTE_DIR"

echo "🔨 Rebuilding and Restarting $SERVICE_NAME..."

# 2. Rebuild and Restart 

ssh "$SERVER_USER@$SERVER_IP" "cd $REMOTE_DIR && docker compose restart $SERVICE_NAME"
ssh "$SERVER_USER@$SERVER_IP" "cd $REMOTE_DIR && docker compose exec app alembic upgrade head"

echo "🔍 Checking logs for errors..."

# 3. Show the last 50 lines of logs to confirm successful startup
ssh "$SERVER_USER@$SERVER_IP" "cd $REMOTE_DIR && docker compose logs $SERVICE_NAME --tail 50"

echo "🎉 Done! If you see 'Uvicorn running', your change is live."