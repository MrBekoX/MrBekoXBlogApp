import { Person, WithContext } from 'schema-dts';
import { JsonLd } from './json-ld';

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'https://mrbekox.dev';

export function PersonSchema() {
  const personSchema: WithContext<Person> = {
    '@context': 'https://schema.org',
    '@type': 'Person',
    name: 'Sample Author',
    alternateName: 'MrBekoX',
    url: SITE_URL,
    image: `${SITE_URL}/images/avatar.jpg`,
    jobTitle: 'Software Developer',
    description: 'Backend geliştirme, yazılım mimarisi ve AI teknolojileri üzerine uzmanlaşmış yazılım geliştirici.',
    sameAs: [
      'https://example.invalid/author',
      'https://example.invalid/social',
      'https://example.invalid/author',
    ],
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
  };

  return <JsonLd data={personSchema} />;
}
