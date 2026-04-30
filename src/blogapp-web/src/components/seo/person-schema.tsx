import { Person, WithContext } from 'schema-dts';
import { JsonLd } from './json-ld';
import {
  SITE_URL,
  SITE_NAME,
  AUTHOR_NAME,
  AUTHOR_JOB_TITLE,
  AUTHOR_DESCRIPTION,
  SOCIAL_URLS,
} from '@/lib/site-config';

export function PersonSchema() {
  const personSchema: WithContext<Person> = {
    '@context': 'https://schema.org',
    '@type': 'Person',
    '@id': `${SITE_URL}/#author`,
    name: AUTHOR_NAME,
    alternateName: SITE_NAME,
    url: SITE_URL,
    image: `${SITE_URL}/images/avatar.jpg`,
    jobTitle: AUTHOR_JOB_TITLE,
    description: AUTHOR_DESCRIPTION,
    sameAs: SOCIAL_URLS,
    worksFor: {
      '@type': 'Organization',
      '@id': `${SITE_URL}/#organization`,
    },
    knowsAbout: [
      'Backend Development',
      'Software Architecture',
      'AI Technologies',
      '.NET',
      'C#',
      'Python',
      'Microservices',
      'Clean Architecture',
      'CQRS',
    ],
  } as WithContext<Person>;

  return <JsonLd data={personSchema} />;
}
