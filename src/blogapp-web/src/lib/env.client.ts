const DEV_API_URL = 'http://localhost:5116/api/v1';

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || DEV_API_URL;

export const BASE_URL = API_BASE_URL.startsWith('/')
  ? ''
  : API_BASE_URL.replace(/\/api(\/v\d+)?\/?$/, '');

const SIGNALR_BASE_URL = process.env.NEXT_PUBLIC_SIGNALR_URL || BASE_URL;

export const PUBLIC_CACHE_HUB_URL = `${SIGNALR_BASE_URL}/hubs/public-cache`;
export const AUTHORING_EVENTS_HUB_URL = `${SIGNALR_BASE_URL}/hubs/authoring-events`;
export const CHAT_EVENTS_HUB_URL = `${SIGNALR_BASE_URL}/hubs/chat-events`;
export const TURNSTILE_SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || '';

export const HUB_URL = PUBLIC_CACHE_HUB_URL;
