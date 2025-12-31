import { WebSite, WithContext } from 'schema-dts';
import { JsonLd } from './json-ld';

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'https://mrbekox.dev';

export function WebsiteSchema() {
  const websiteSchema: WithContext<WebSite> = {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: 'MrBekoX Blog',
    url: SITE_URL,
    description:
      'Backend geliştirme, yazılım mimarisi ve AI teknolojileri üzerine teknik içerikler.',
    potentialAction: {
      '@type': 'SearchAction',
      target: {
        '@type': 'EntryPoint',
        urlTemplate: `${SITE_URL}/posts?search={search_term_string}`,
      },
      'query-input': 'required name=search_term_string',
    } as any, // query-input is valid Schema.org but not in schema-dts types
    inLanguage: 'tr-TR',
  };

  return <JsonLd data={websiteSchema} />;
}
