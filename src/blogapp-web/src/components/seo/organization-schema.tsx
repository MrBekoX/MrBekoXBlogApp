import { Organization, WithContext } from 'schema-dts';
import { JsonLd } from './json-ld';

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'https://mrbekox.dev';

export function OrganizationSchema() {
  const organizationSchema: WithContext<Organization> = {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    name: 'MrBekoX',
    url: SITE_URL,
    logo: `${SITE_URL}/images/avatar.jpg`,
    sameAs: [
      'https://github.com/MrBekoX',
      'https://x.com/mrbeko_',
      'https://www.linkedin.com/in/berkay-kaplan-133b35245/',
    ],
    description:
      'Backend geliştirme, yazılım mimarisi ve AI teknolojileri üzerine teknik içerikler paylaşan blog platformu.',
  };

  return <JsonLd data={organizationSchema} />;
}
