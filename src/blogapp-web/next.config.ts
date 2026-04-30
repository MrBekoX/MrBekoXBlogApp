import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // SSR mode with standalone output for Docker deployment
  output: 'standalone',

  // Enable image optimization with remote patterns
  images: {
    // Use 'unoptimized' for Docker to avoid image fetch issues
    // Next.js image optimizer can't fetch from localhost:8080 inside container
    unoptimized: true,

    remotePatterns: [
      {
        protocol: (process.env.NEXT_PUBLIC_IMAGE_PROTOCOL as 'http' | 'https') || 'https',
        hostname: process.env.NEXT_PUBLIC_IMAGE_HOSTNAME || 'mrbekox.dev',
        pathname: '/uploads/**',
      },
      {
        protocol: 'http',
        hostname: process.env.NEXT_PUBLIC_IMAGE_DEV_HOSTNAME || 'localhost',
        port: process.env.NEXT_PUBLIC_IMAGE_DEV_PORT || '8080',
        pathname: '/uploads/**',
      },
      {
        protocol: 'http',
        hostname: process.env.NEXT_PUBLIC_IMAGE_DOCKER_HOSTNAME || 'backend',
        port: process.env.NEXT_PUBLIC_IMAGE_DOCKER_PORT || '8080',
        pathname: '/uploads/**',
      },
    ],
  },

  // Disable trailing slashes for cleaner URLs
  trailingSlash: false,

  // Skip build-time type checking (optional, for faster builds)
  typescript: {
    ignoreBuildErrors: false,
  },

  // Experimental features
  experimental: {
    // Optimize CSS chunking to reduce preload warnings
    cssChunking: 'strict',
    // Disable client-side Router Cache so navigations always get fresh RSC payload
    staleTimes: {
      dynamic: 0,
      static: 30,
    },
    // FIX: Increase page data bytes limit to prevent content truncation
    largePageDataBytes: 128000, // 128KB - increase if needed for large content
  },

  // Proxy API/hub/uploads requests to backend (eliminates cross-origin cookie issues)
  async rewrites() {
    const backendUrl = process.env.REWRITE_URL || 'http://localhost:5116';
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: '/hubs/:path*',
        destination: `${backendUrl}/hubs/:path*`,
      },
      {
        source: '/uploads/:path*',
        destination: `${backendUrl}/uploads/:path*`,
      },
    ];
  },

  async headers() {
    return [
      {
        // Security headers for all routes
        source: '/:path*',
        headers: [
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
          { key: 'Content-Security-Policy', value: "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://challenges.cloudflare.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: http: https: blob:; connect-src 'self' ws: wss: http: https:; frame-src https://challenges.cloudflare.com; frame-ancestors 'self'; base-uri 'self'; form-action 'self'" },
          { key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains; preload' },
        ],
      },
      {
        // Prevent browser from caching SSR HTML pages — ensures F5 always gets fresh content
        source: '/((?!_next/static|_next/image|favicon\\.ico|uploads).*)',
        headers: [
          { key: 'Cache-Control', value: 'no-store, no-cache, must-revalidate, proxy-revalidate' },
        ],
      },
    ];
  },
};

export default nextConfig;
