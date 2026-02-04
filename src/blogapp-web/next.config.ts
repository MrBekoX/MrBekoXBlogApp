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
    // Optimize CSS to reduce unused preload warnings
    optimizeCss: true,
  },

  // Cache lifetime profiles for revalidateTag
  cacheLife: {
    default: {
      stale: 60,
      revalidate: 300,
      expire: 86400,
    },
    posts: {
      stale: 30,
      revalidate: 60,
      expire: 3600,
    },
    categories: {
      stale: 300,
      revalidate: 600,
      expire: 86400,
    },
    tags: {
      stale: 300,
      revalidate: 600,
      expire: 86400,
    },
  },
};

export default nextConfig;
