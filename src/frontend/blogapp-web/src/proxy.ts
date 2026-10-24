import { randomBytes } from 'node:crypto';
import { NextResponse, type NextRequest } from 'next/server';
import { buildContentSecurityPolicy, buildMermaidRendererSecurityPolicy } from './lib/security/content-security-policy';

/** HTML policy authority: fresh trusted nonce per request, never a client nonce. */
export function proxy(request: NextRequest) {
  const nonce = randomBytes(16).toString('base64');
  const contentSecurityPolicy = request.nextUrl.pathname === '/mermaid-renderer'
    ? buildMermaidRendererSecurityPolicy(nonce)
    : buildContentSecurityPolicy(nonce, {
    development: process.env.NODE_ENV === 'development',
    siteUrl: process.env.NEXT_PUBLIC_SITE_URL,
    apiUrl: process.env.NEXT_PUBLIC_API_URL,
    signalRUrl: process.env.NEXT_PUBLIC_SIGNALR_URL,
    // Compatibility for a future explicitly configured widget only. This does
    // not install a widget or claim CAPTCHA is enforced by this application.
    turnstileConfigured: Boolean(process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY?.trim()),
  });
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('x-nonce', nonce);
  requestHeaders.set('Content-Security-Policy', contentSecurityPolicy);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set('Content-Security-Policy', contentSecurityPolicy);
  response.headers.set('X-Frame-Options', request.nextUrl.pathname === '/mermaid-renderer' ? 'SAMEORIGIN' : 'DENY');
  response.headers.set('Cache-Control', 'private, no-store, max-age=0, must-revalidate');
  return response;
}

export const config = {
  // Backend responses own their API policy; static resources keep their normal
  // immutable caching. Every HTML route, including 404s, receives a new nonce.
  matcher: ['/((?!mermaid-renderer/mermaid\\.js$|api(?:/|$)|hubs(?:/|$)|uploads(?:/|$)|_next/static(?:/|$)|_next/image(?:/|$)|favicon\\.ico$|icon\\.png$|robots\\.txt$|sitemap\\.xml$|llms\\.txt$|rss$|feed$|feed\\.xml$).*)'],
};
