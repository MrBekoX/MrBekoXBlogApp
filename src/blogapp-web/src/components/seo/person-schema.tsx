import { Person, WithContext } from 'schema-dts';
import { JsonLd } from './json-ld';

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'https://mrbekox.dev';

export function PersonSchema() {
  const personSchema: WithContext<Person> = {
    '@context': 'https://schema.org',
    '@type': 'Person',
    name: 'Berkay Kaplan',
    alternateName: 'MrBekoX',
    url: SITE_URL,
    image: `${SITE_URL}/images/avatar.jpg`,
    jobTitle: 'Software Developer',
    description: 'Backend geliştirme, yazılım mimarisi ve AI teknolojileri üzerine uzmanlaşmış yazılım geliştirici.',
    sameAs: [
      'https://github.com/MrBekoX',
      'https://x.com/mrbeko_',
      'https://www.linkedin.com/in/berkay-kaplan-133b35245/',
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
