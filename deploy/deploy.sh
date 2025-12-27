#!/bin/bash
set -e

echo "🚀 BlogApp Deployment - Pull Mode"
source .env

# Private Repo girişi kontrolü
echo "📥 Step 1: Pulling latest images..."
docker compose -f docker-compose.prod.yml pull

echo "🔨 Step 2: Restarting containers..."
# --build kaldırıldı, sadece çalıştırır
docker compose -f docker-compose.prod.yml up -d

echo "📦 Step 3: Running migrations..."
docker compose -f docker-compose.prod.yml exec -T api dotnet ef database update || echo "⚠️ Migration skip/fail"

echo "✅ Success!"
docker compose -f docker-compose.prod.yml ps