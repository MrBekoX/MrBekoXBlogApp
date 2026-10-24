import { mermaidRendererDocument } from '@/lib/security/mermaid-renderer-document';
import { loadInlineMermaidBundle } from '@/lib/security/mermaid-bundle.server';
import mermaidPackage from 'mermaid/package.json';
import { isIP } from 'node:net';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function isLoopbackRequest(request: Request): boolean {
  try {
    const host = request.headers.get('host');
    const hostname = new URL(host ? 'http://' + host : request.url).hostname.toLowerCase().replace(/\.$/, '');
    return hostname === 'localhost' || hostname.endsWith('.localhost') || hostname === '[::1]'
      || (isIP(hostname) === 4 && hostname.startsWith('127.'));
  } catch {
    return false;
  }
}

export async function GET(request: Request) {
  const nonce = request.headers.get('x-nonce');
  if (!nonce) return new Response('Renderer requires the trusted nonce proxy.', { status: 500 });
  // An opaque iframe cannot request loopback scripts under Chrome's Local
  // Network Access policy. Embed only the trusted package in local documents;
  // public production hosts keep the small document and cached external asset.
  const inlineBundle = process.env.NODE_ENV === 'development' || isLoopbackRequest(request)
    ? await loadInlineMermaidBundle() : undefined;
  return new Response(mermaidRendererDocument(nonce, mermaidPackage.version, inlineBundle), {
    headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'private, no-store', 'X-Frame-Options': 'SAMEORIGIN' },
  });
}
