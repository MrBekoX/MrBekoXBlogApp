# Build stage
# Consider pinning: node:20.11.0-alpine3.19
FROM node:20-alpine AS build
WORKDIR /app

# Copy package files and install dependencies first (cache-friendly)
COPY package*.json ./
RUN npm ci

# Copy source files
COPY . ./

# Accept build arguments for API URLs (after npm ci to preserve cache)
ARG NEXT_PUBLIC_API_URL=http://localhost:8080/api/v1
ARG NEXT_PUBLIC_SIGNALR_URL=
ARG API_URL=http://localhost:8080/api/v1
ARG REWRITE_URL=http://localhost:5116

ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_PUBLIC_SIGNALR_URL=${NEXT_PUBLIC_SIGNALR_URL}
ENV API_URL=${API_URL}
ENV REWRITE_URL=${REWRITE_URL}

# Build application (standalone output)
RUN npm run build

# Production stage
# Consider pinning: node:20.11.0-alpine3.19
FROM node:20-alpine AS runtime
WORKDIR /app

# Create non-root user for security
RUN addgroup -g 1001 -S nodejs && \
    adduser -S nextjs -u 1001

# Copy standalone build output
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nodejs /app/public ./public

# Switch to non-root user
USER nextjs

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000/ || exit 1

# Set Node environment
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
