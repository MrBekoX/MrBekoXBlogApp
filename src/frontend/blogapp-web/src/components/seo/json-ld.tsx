import { headers } from 'next/headers';
import { Thing, WithContext } from 'schema-dts';

interface JsonLdProps {
  data: WithContext<Thing> | WithContext<Thing>[];
}

function escapeJsonLd(value: string): string {
  return value
    .replace(/<\//g, '<\\/')
    .replace(/</g, '\\u003C')
    .replace(/>/g, '\\u003E')
    .replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
}

export async function JsonLd({ data }: JsonLdProps) {
  const nonce = (await headers()).get('x-nonce') ?? undefined;
  const jsonString = escapeJsonLd(JSON.stringify(data));

  return (
    <script
      type="application/ld+json"
      nonce={nonce}
      dangerouslySetInnerHTML={{
        __html: jsonString,
      }}
    />
  );
}
