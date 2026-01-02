FROM node:20-alpine AS base

# Install dependencies only when needed
FROM base AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

# Rebuild the source code only when needed
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build-time argument for API URL (NEXT_PUBLIC_* vars are baked at build time)
ARG NEXT_PUBLIC_API_URL=https://mrbekox.dev/api/v1
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# Production image - serve static files with nginx
FROM nginx:alpine AS runner

# Copy static build output from 'out' folder (created by 'output: export')
COPY --from=builder /app/out /usr/share/nginx/html

# Copy custom nginx config for SPA routing
COPY nginx.docker.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
