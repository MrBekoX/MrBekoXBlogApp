import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Enable static export for true SPA behavior
  output: 'export',
  
  // Disable image optimization for static export
  images: {
    unoptimized: true,
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
};

export default nextConfig;
