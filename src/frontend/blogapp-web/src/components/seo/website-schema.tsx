import type { SearchAction, WebSite, WithContext } from 'schema-dts';
import { JsonLd } from './json-ld';
import { SITE_URL, SITE_NAME, SITE_DESCRIPTION } from '@/lib/site-config';

export function WebsiteSchema() {
  const searchAction: SearchAction & { 'query-input': string } = {
    '@type': 'SearchAction',
    target: {
      '@type': 'EntryPoint',
      urlTemplate: `${SITE_URL}/posts?search={search_term_string}`,
    },
    'query-input': 'required name=search_term_string',
  };
  const websiteSchema: WithContext<WebSite> = {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: `${SITE_NAME} Blog`,
    url: SITE_URL,
    description: SITE_DESCRIPTION,
    potentialAction: searchAction,
    inLanguage: 'tr-TR',
  };

  return <JsonLd data={websiteSchema} />;
}
