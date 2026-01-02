import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Enable static export for true SPA behavior
  output: 'export',
  
  // Disable image optimization for static export
  // You can use external image CDN or unoptimized images
  images: {
    unoptimized: true,
  },
  
  // Disable trailing slashes for cleaner URLs
  trailingSlash: false,
  
  // Skip build-time type checking (optional, for faster builds)
  typescript: {
    ignoreBuildErrors: false,
  },
};

export default nextConfig;
