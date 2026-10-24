import { Organization, WithContext } from 'schema-dts';
import { JsonLd } from './json-ld';
import {
  SITE_URL,
  SITE_NAME,
  SITE_DESCRIPTION,
  SOCIAL_URLS,
} from '@/lib/site-config';

export function OrganizationSchema() {
  const organizationSchema: WithContext<Organization> = {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    '@id': `${SITE_URL}/#organization`,
    name: SITE_NAME,
    url: SITE_URL,
    logo: {
      '@type': 'ImageObject',
      url: `${SITE_URL}/images/avatar.jpg`,
    },
    ...(SOCIAL_URLS.length ? { sameAs: SOCIAL_URLS } : {}),
    description: SITE_DESCRIPTION,
  } as WithContext<Organization>;

  return <JsonLd data={organizationSchema} />;
}
