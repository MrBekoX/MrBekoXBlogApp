import { describe, expect, it } from 'vitest';
import { discoveryRewrites } from './discovery-rewrites';

describe('discoveryRewrites', () => {
  it('proxies AI and feed documents to the backend origin', () => {
    expect(discoveryRewrites('http://localhost:5116/')).toEqual([
      { source: '/llms.txt', destination: 'http://localhost:5116/llms.txt' },
      { source: '/rss', destination: 'http://localhost:5116/rss' },
      { source: '/feed', destination: 'http://localhost:5116/feed' },
      { source: '/feed.xml', destination: 'http://localhost:5116/feed.xml' },
    ]);
  });

  it('leaves sitemap and robots on the Next.js metadata routes', () => {
    const sources = discoveryRewrites('http://backend:8080').map((rule) => rule.source);
    expect(sources).not.toContain('/sitemap.xml');
    expect(sources).not.toContain('/robots.txt');
  });
});
