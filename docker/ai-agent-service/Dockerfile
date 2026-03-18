# Stage 1: Install Python dependencies (with build tools)
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build tools only in builder stage
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

# Stage 2: Production image (slim, no build tools)
FROM python:3.12-slim AS production

WORKDIR /app

# Install only runtime dependencies (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user for security
RUN groupadd -g 1001 appgroup && \
    useradd -u 1001 -g appgroup -s /bin/bash -m appuser

# Copy application code
COPY --chown=appuser:appgroup ./app ./app

# Create data directories for persistence
RUN mkdir -p /app/data /app/chroma_data && \
    chown -R appuser:appgroup /app/data /app/chroma_data && \
    chmod 750 /app/chroma_data

# Switch to non-root user
USER appuser

# Expose FastAPI port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run FastAPI with uvicorn
CMD ["python", "-m", "app.main"]
