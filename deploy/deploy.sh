#!/bin/bash

# BlogApp Deployment Script
# This script helps deploy the application to production

set -e

echo "🚀 BlogApp Deployment Script"
echo "============================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠️  .env file not found!${NC}"
    echo "Creating .env from env.template..."
    if [ -f env.template ]; then
        cp env.template .env
        echo -e "${YELLOW}⚠️  Please edit .env file with your production values before continuing!${NC}"
        exit 1
    else
        echo -e "${RED}❌ env.template file not found!${NC}"
        exit 1
    fi
fi

# Check if required environment variables are set
source .env

if [ -z "$POSTGRES_PASSWORD" ] || [ "$POSTGRES_PASSWORD" = "your_strong_password_here_change_this" ]; then
    echo -e "${RED}❌ POSTGRES_PASSWORD must be set in .env file!${NC}"
    exit 1
fi

if [ -z "$JWT_SECRET" ] || [ "$JWT_SECRET" = "your_super_secret_key_at_least_64_characters_long_change_this_now" ]; then
    echo -e "${RED}❌ JWT_SECRET must be set in .env file!${NC}"
    exit 1
fi

if [ -z "$ADMIN_PASSWORD" ] || [ "$ADMIN_PASSWORD" = "your_strong_admin_password_min_12_chars" ]; then
    echo -e "${RED}❌ ADMIN_PASSWORD must be set in .env file!${NC}"
    exit 1
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker is not installed!${NC}"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker compose &> /dev/null; then
    echo -e "${RED}❌ Docker Compose is not installed!${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Prerequisites check passed${NC}"

# Function to run database migrations
run_migrations() {
    echo ""
    echo "📦 Running database migrations..."
    docker compose -f docker-compose.prod.yml exec -T api dotnet ef database update --project /src/BlogApp.Server.Infrastructure --startup-project /src/BlogApp.Server.Api || {
        echo -e "${YELLOW}⚠️  Migration command not available. You may need to run migrations manually.${NC}"
    }
}

# Main deployment function
deploy() {
    echo ""
    echo "🔨 Building and starting containers..."
    docker compose -f docker-compose.prod.yml --env-file .env up -d --build

    echo ""
    echo "⏳ Waiting for services to be healthy..."
    sleep 10

    # Wait for postgres to be ready
    echo "Waiting for PostgreSQL..."
    timeout=60
    counter=0
    until docker compose -f docker-compose.prod.yml exec -T postgres pg_isready -U ${POSTGRES_USER:-blogapp_user} > /dev/null 2>&1; do
        if [ $counter -ge $timeout ]; then
            echo -e "${RED}❌ PostgreSQL failed to start within ${timeout} seconds${NC}"
            exit 1
        fi
        echo -n "."
        sleep 2
        counter=$((counter + 2))
    done
    echo -e "${GREEN}✅ PostgreSQL is ready${NC}"

    # Run migrations
    run_migrations

    echo ""
    echo -e "${GREEN}✅ Deployment completed successfully!${NC}"
    echo ""
    echo "📊 Service Status:"
    docker compose -f docker-compose.prod.yml ps
    echo ""
    echo "📝 View logs with: docker compose -f docker-compose.prod.yml logs -f"
    echo "🛑 Stop services with: docker compose -f docker-compose.prod.yml down"
}

# Function to stop services
stop() {
    echo "🛑 Stopping services..."
    docker compose -f docker-compose.prod.yml --env-file .env down
    echo -e "${GREEN}✅ Services stopped${NC}"
}

# Function to view logs
logs() {
    docker compose -f docker-compose.prod.yml logs -f "$@"
}

# Function to restart services
restart() {
    echo "🔄 Restarting services..."
    docker compose -f docker-compose.prod.yml --env-file .env restart
    echo -e "${GREEN}✅ Services restarted${NC}"
}

# Parse command line arguments
case "${1:-deploy}" in
    deploy)
        deploy
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    logs)
        logs "${@:2}"
        ;;
    migrate)
        run_migrations
        ;;
    *)
        echo "Usage: $0 {deploy|stop|restart|logs|migrate}"
        echo ""
        echo "Commands:"
        echo "  deploy   - Build and start all services (default)"
        echo "  stop     - Stop all services"
        echo "  restart  - Restart all services"
        echo "  logs     - View logs (optionally specify service name)"
        echo "  migrate  - Run database migrations"
        exit 1
        ;;
esac

