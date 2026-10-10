export const PUBLIC_DISCOVERY_PATHS = ['/llms.txt', '/rss', '/feed', '/feed.xml'] as const;

export function discoveryRewrites(backendUrl: string): { source: string; destination: string }[] {
  const origin = backendUrl.replace(/\/$/, '');
  return PUBLIC_DISCOVERY_PATHS.map((source) => ({
    source,
    destination: `${origin}${source}`,
  }));
}
