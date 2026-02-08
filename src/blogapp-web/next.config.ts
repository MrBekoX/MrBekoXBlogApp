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
        protocol: 'https',
        hostname: 'mrbekox.dev',
        pathname: '/uploads/**',
      },
      {
        protocol: 'http',
        hostname: 'localhost',
        port: '8080',
        pathname: '/uploads/**',
      },
      {
        protocol: 'http',
        hostname: 'backend',
        port: '8080',
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
  },
};

export default nextConfig;
