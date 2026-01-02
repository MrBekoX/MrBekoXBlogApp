# PostgreSQL Search Optimization Migration Script Runner
# This script applies the migration to PostgreSQL in Docker container

Write-Host "Starting search optimization migration..." -ForegroundColor Cyan

# Docker container name (from docker-compose.yml)
$CONTAINER_NAME = "blogapp-postgres"
$DB_NAME = "blogdb_dev"
$DB_USER = "blogapp_user"
$SQL_FILE = "src\BlogApp.Server\BlogApp.Server.Infrastructure\Persistence\Migrations\SearchOptimization.sql"

# Check if container is running
$containerRunning = docker ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}"
if (-not $containerRunning) {
    Write-Host "ERROR: PostgreSQL container ($CONTAINER_NAME) is not running!" -ForegroundColor Red
    Write-Host "TIP: Start the container first with 'docker-compose up -d'" -ForegroundColor Yellow
    exit 1
}

Write-Host "Container found: $CONTAINER_NAME" -ForegroundColor Green

# Copy SQL file to container and execute
Write-Host "Copying SQL script to container..." -ForegroundColor Cyan

# Copy file to container
docker cp $SQL_FILE "${CONTAINER_NAME}:/tmp/SearchOptimization.sql"

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to copy SQL file to container!" -ForegroundColor Red
    exit 1
}

Write-Host "Executing SQL script..." -ForegroundColor Cyan

# Execute script
docker exec -i $CONTAINER_NAME psql -U $DB_USER -d $DB_NAME -f /tmp/SearchOptimization.sql

if ($LASTEXITCODE -eq 0) {
    Write-Host "Migration applied successfully!" -ForegroundColor Green
    Write-Host "Search optimization is now active!" -ForegroundColor Green
} else {
    Write-Host "ERROR: An error occurred during migration!" -ForegroundColor Red
    exit 1
}

# Clean up temporary file
docker exec $CONTAINER_NAME rm /tmp/SearchOptimization.sql

Write-Host "Process completed!" -ForegroundColor Green
