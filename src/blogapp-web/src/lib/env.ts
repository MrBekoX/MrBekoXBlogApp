// Backward-compatible re-export of client-safe environment variables.
// New code should import directly from:
//   '@/lib/env.client' for client components
//   '@/lib/env.server' for server components (SERVER_API_URL)

export { API_BASE_URL, BASE_URL, HUB_URL } from './env.client';
