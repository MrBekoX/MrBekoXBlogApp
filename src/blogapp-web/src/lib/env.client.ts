// Client-safe environment configuration
// Safe to import from client components — no server-only variables.

const DEV_API_URL = 'http://localhost:5116/api/v1';

/**
 * API Base URL (with /api/v1 suffix).
 * - Client-side: reads NEXT_PUBLIC_API_URL
 * - Falls back to localhost for development
 */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || DEV_API_URL;

/**
 * Base URL without /api/v1 suffix.
 * Used for SignalR hubs and other non-API endpoints.
 */
export const BASE_URL = API_BASE_URL.replace(/\/api(\/v\d+)?\/?$/, '');

/**
 * SignalR Hub URL for real-time features (cache sync, chat, AI analysis).
 */
export const HUB_URL = `${BASE_URL}/hubs/cache`;
