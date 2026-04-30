# Docker Configuration

This directory contains all Docker-related configuration files for the BlogApp project.

## Directory Structure

```
docker/
├── .env.example            # Environment variables template
├── backend/
│   └── Dockerfile          # .NET Backend API Dockerfile
├── frontend/
│   └── Dockerfile          # Next.js Frontend Dockerfile
├── docker-compose.yml      # Service orchestration
└── README.md               # This file
```

## Services

| Service | Technology | Port | Description |
|---|---|---|---|
| **postgres** | PostgreSQL 18 Alpine | 5432 | Primary database |
| **redis** | Redis 8 Alpine | 6379 | Cache (L1/L2 hybrid) |
| **backend** | .NET 10 (ASP.NET Core) | 8080 | REST API + SignalR hubs |
| **frontend** | Next.js 16 (standalone) | 3000 | SSR frontend |

## Quick Start

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your values

# 2. Build and run
docker compose up -d --build

# 3. Check status
docker compose ps
```

## Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Required | Description |
|---|---|---|
| `POSTGRES_USER` | Yes | PostgreSQL username |
| `POSTGRES_PASSWORD` | Yes | PostgreSQL password |
| `POSTGRES_DB` | No | Database name (default: `blogdb`) |
| `REDIS_PASSWORD` | Yes | Redis password |
| `JwtSettings__Secret` | Yes | JWT secret (min 32 chars) |
| `ADMIN_EMAIL` | No | Initial admin email |
| `ADMIN_USERNAME` | No | Initial admin username |
| `ADMIN_PASSWORD` | No | Initial admin password |
| `ALLOWED_HOSTS` | Yes | Host header validation |
| `CORS_ORIGIN_0` | No | Frontend URL for CORS |
| `PUBLIC_SIGNALR_URL` | No | SignalR URL for browser |
| `TURNSTILE_SITE_KEY` | No | Cloudflare Turnstile key |

## Commands

```bash
# Build specific service
docker compose build backend
docker compose build frontend

# View logs
docker compose logs -f
docker compose logs -f backend

# Stop all
docker compose down

# Clean rebuild
docker compose down -v
docker compose up -d --build
```

## Health Checks

- **Backend:** `http://localhost:8080/health` (PostgreSQL + Redis)
- **Frontend:** `http://localhost:3000`

## Architecture

```
Browser → frontend:3000 → (next.config.ts rewrites) → backend:8080
                                                          ├── postgres:5432
                                                          └── redis:6379
```

Frontend proxies `/api/*`, `/hubs/*`, `/uploads/*` to the backend via Next.js rewrites.

## Production Notes

1. All services run as non-root users
2. Multi-stage builds minimize image size
3. Health checks enable automated monitoring
4. `Database__RunMigrationsOnStartup=true` runs EF Core migrations on backend start
5. Use strong passwords — generate with `openssl rand -base64 32`
