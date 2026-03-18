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
};

export default nextConfig;
