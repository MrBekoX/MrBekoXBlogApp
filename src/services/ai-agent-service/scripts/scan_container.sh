#!/bin/bash
# Scan Docker image for vulnerabilities

set -e

IMAGE="${1:-blogapp-ai-agent:hardened}"

echo "Scanning image: $IMAGE"

# Check with Docker Scout (if available)
if command -v docker scout &> /dev/null; then
  echo "Running Docker Scout..."
  docker scout cves "$IMAGE"
fi

# Check with Trivy (if available)
if command -v trivy &> /dev/null; then
  echo "Running Trivy..."
  trivy image --severity HIGH,CRITICAL "$IMAGE"
fi

# Check image configuration
echo "Checking image configuration..."
docker inspect "$IMAGE" | jq '.[0].Config'

# Check security options
echo "Checking user..."
USER=$(docker inspect "$IMAGE" | jq -r '.[0].Config.User')
if [ "$USER" = "root" ] || [ -z "$USER" ]; then
  echo "⚠️  WARNING: Container runs as root!"
else
  echo "✅ Container runs as non-root user: $USER"
fi
