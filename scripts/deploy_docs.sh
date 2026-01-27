#!/bin/bash

# Configuration
APP_NAME="mira-docs"
REGION="us-central1" # Change if needed

# Check for Project ID
if [ -z "$GCP_PROJECT_ID" ]; then
    echo "Error: GCP_PROJECT_ID environment variable is not set."
    echo "Usage: GCP_PROJECT_ID=your-project-id ./scripts/deploy_docs.sh"
    exit 1
fi

echo "========================================================"
echo "Deploying $APP_NAME to Google Cloud Run"
echo "Project: $GCP_PROJECT_ID"
echo "Region:  $REGION"
echo "========================================================"

# 1. Build the Docker image
echo "[1/3] Building Docker image..."
docker build -t gcr.io/$GCP_PROJECT_ID/$APP_NAME -f Dockerfile.docs .

# 2. Push to Google Container Registry
echo "[2/3] Pushing image to GCR..."
docker push gcr.io/$GCP_PROJECT_ID/$APP_NAME

# 3. Deploy to Cloud Run
echo "[3/3] Deploying to Cloud Run..."
gcloud run deploy $APP_NAME \
    --image gcr.io/$GCP_PROJECT_ID/$APP_NAME \
    --platform managed \
    --region $REGION \
    --allow-unauthenticated \
    --port 80

echo "========================================================"
echo "Deployment Complete!"
echo "To map your domain, go to the Cloud Run console, select '$APP_NAME', and click 'Manage Custom Domains'."
echo "Map 'docs.miraproject.online' to this service."
echo "========================================================"
