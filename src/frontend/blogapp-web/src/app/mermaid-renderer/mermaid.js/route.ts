import { loadMermaidBundle } from '@/lib/security/mermaid-bundle.server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(request: Request) {
  const asset = await loadMermaidBundle();
  const headers = { 'Content-Type': 'application/javascript; charset=utf-8', 'Cache-Control': 'public, max-age=86400, immutable', ETag: asset.etag, 'X-Content-Type-Options': 'nosniff' };
  if (request.headers.get('if-none-match') === asset.etag) return new Response(null, { status: 304, headers });
  return new Response(asset.bytes, { headers });
}
