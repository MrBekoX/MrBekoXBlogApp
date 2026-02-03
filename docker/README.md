# Docker Configuration

This directory contains all Docker-related configuration files for the BlogApp project.

## Directory Structure

```
docker/
├── backend/
│   ├── Dockerfile          # .NET Backend API Dockerfile
│   └── .dockerignore       # Files to exclude from backend build
├── frontend/
│   ├── Dockerfile          # Next.js Frontend Dockerfile
│   └── .dockerignore       # Files to exclude from frontend build
├── ai-agent-service/
│   ├── Dockerfile          # Python AI Agent Service Dockerfile
│   └── .dockerignore       # Files to exclude from AI service build
└── README.md               # This file
```

## Services

### Backend
- **Technology:** .NET 10.0 (ASP.NET Core)
- **Port:** 8080
- **Build:** Multi-stage build with SDK and runtime images
- **Features:**
  - Non-root user for security
  - Health check endpoint
  - Optimized image size

### Frontend
- **Technology:** Next.js 16 (React)
- **Port:** 3000
- **Build:** Multi-stage build with production-optimized image
- **Features:**
  - pnpm for dependency management
  - Non-root user for security
  - Static asset optimization

### AI Agent Service
- **Technology:** Python 3.12 (FastAPI)
- **Port:** 8000
- **Build:** Multi-stage build with dependency caching
- **Features:**
  - LangChain for AI/LLM integration
  - RabbitMQ messaging
  - Redis caching
  - ChromaDB for vector storage

## Usage

### Build All Services
```bash
docker-compose build
```

### Build Specific Service
```bash
docker-compose build backend
docker-compose build frontend
docker-compose build ai-agent-service
```

### Run All Services
```bash
docker-compose up -d
```

### Run Specific Service
```bash
docker-compose up backend
```

### Stop All Services
```bash
docker-compose down
```

### View Logs
```bash
docker-compose logs -f
docker-compose logs -f backend
```

## Environment Variables

Before running, make sure to copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Required variables:
- `POSTGRES_USER` - PostgreSQL username
- `POSTGRES_PASSWORD` - PostgreSQL password
- `JwtSettings__Secret` - JWT token secret

## Health Checks

All services include health checks:
- **Backend:** `http://localhost:8080/health`
- **Frontend:** `http://localhost:3000`
- **AI Service:** `http://localhost:8000/health`

Check service health:
```bash
docker-compose ps
```

## Development

### Hot Reloading
For development with hot reloading, mount volumes:
```yaml
volumes:
  - ./src/BlogApp.Server:/app/src
```

### Debugging
Attach to running container:
```bash
docker-compose exec backend bash
docker-compose exec frontend sh
docker-compose exec ai-agent-service bash
```

## Production Considerations

1. **Security:** All services run as non-root users
2. **Image Size:** Multi-stage builds minimize final image size
3. **Health Checks:** Automated health monitoring
4. **Resource Limits:** Configure in docker-compose.yml if needed
5. **Secrets:** Use Docker secrets or external vault for production

## Troubleshooting

### Build Failures
- Clear Docker cache: `docker system prune -a`
- Check disk space: `docker system df`

### Service Not Starting
- Check logs: `docker-compose logs [service]`
- Verify environment variables
- Check port conflicts

### Permission Issues
- All services run as non-root users
- Ensure proper file permissions on mounted volumes

## Additional Resources

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [.NET Docker Samples](https://github.com/dotnet/dotnet-docker)
- [Next.js Deployment](https://nextjs.org/docs/deployment)
