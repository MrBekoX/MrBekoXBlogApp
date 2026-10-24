// Exact trusted CSS emitted by the pinned Sonner 2.0.7 runtime. A regression
// test verifies this hash against the installed library when dependencies change.
// Sonner appends its empty style element before filling the known stylesheet.
// This hash authorizes no CSS rules; subsequent content still needs its own hash.
export const EMPTY_STYLE_HASH = "'sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU='";
export const SONNER_STYLE_HASH = "'sha256-CIxDM5jnsGiKqXs2v7NKCY5MzdR9gu6TtiMJrDw29AY='";

export interface ContentSecurityPolicyOptions {
  development: boolean;
  siteUrl?: string;
  apiUrl?: string;
  signalRUrl?: string;
  turnstileConfigured?: boolean;
}

function configuredHttpOrigin(value: string | undefined): string | null {
  if (!value?.trim() || value.trim().startsWith('/')) return null;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    return url.origin;
  } catch {
    return null;
  }
}

export function buildContentSecurityPolicy(nonce: string, options: ContentSecurityPolicyOptions): string {
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(nonce)) throw new Error('CSP nonce must be server-generated base64.');

  const connectSources = new Set(["'self'"]);
  for (const configured of [options.siteUrl, options.apiUrl, options.signalRUrl]) {
    const origin = configuredHttpOrigin(configured);
    if (origin) {
      connectSources.add(origin);
      connectSources.add(origin.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:'));
    }
  }
  // Next dev uses a local WebSocket for HMR. Production permits only explicit
  // configured origins above, plus the current document's same-origin requests.
  if (options.development) {
    connectSources.add('ws://localhost:*');
    connectSources.add('ws://127.0.0.1:*');
  }

  const cloudflare = options.turnstileConfigured ? 'https://challenges.cloudflare.com' : null;
  if (cloudflare) connectSources.add(cloudflare);
  const scriptSources = ["'self'", "'nonce-" + nonce + "'", "'strict-dynamic'"];
  if (options.development) scriptSources.push("'unsafe-eval'");
  if (cloudflare) scriptSources.push(cloudflare);

  return [
    "default-src 'self'",
    'script-src ' + scriptSources.join(' '),
    "script-src-attr 'none'",
    "style-src 'self' " + (options.development ? "'unsafe-inline'" : "'nonce-" + nonce + "' " + SONNER_STYLE_HASH + " " + EMPTY_STYLE_HASH) + " https://fonts.googleapis.com",
    // React/Radix and rendered markdown use legitimate style attributes.
    // This exception permits CSS attributes only, never scripts or style tags.
    "style-src-attr 'unsafe-inline'",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob: http: https:",
    'connect-src ' + [...connectSources].join(' '),
    "frame-src 'self'" + (cloudflare ? ' ' + cloudflare : ''),
    "worker-src 'self' blob:",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join('; ');
}

/** No application state or parent DOM exists in this opaque sandbox document. */
export function buildMermaidRendererSecurityPolicy(nonce: string): string {
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(nonce)) throw new Error('CSP nonce must be server-generated base64.');
  return [
    "default-src 'none'",
    "script-src 'nonce-" + nonce + "' 'strict-dynamic'",
    "script-src-attr 'none'",
    "style-src 'unsafe-inline'",
    "img-src data: blob:",
    "font-src 'none'",
    "connect-src 'none'",
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'self'",
    'sandbox allow-scripts',
  ].join('; ');
}
