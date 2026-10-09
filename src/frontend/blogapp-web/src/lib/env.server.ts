import 'server-only';

// Server-only environment configuration
// This file MUST NOT be imported from client components.

const DEV_API_URL = 'http://localhost:5116/api/v1';

/**
 * Server-side API URL (for SSR/RSC).
 * - Prefers API_URL (internal Docker network URL)
 * - Falls back to NEXT_PUBLIC_API_URL (public URL)
 * - Falls back to localhost for development
 */
export const SERVER_API_URL = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || DEV_API_URL;
