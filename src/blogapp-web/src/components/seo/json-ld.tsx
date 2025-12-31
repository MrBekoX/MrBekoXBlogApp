import { Thing, WithContext } from 'schema-dts';

interface JsonLdProps {
  data: WithContext<Thing> | WithContext<Thing>[];
}

/**
 * Component for embedding JSON-LD structured data in the document head.
 * Supports single schema or array of schemas.
 */
export function JsonLd({ data }: JsonLdProps) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(data, null, 0),
      }}
    />
  );
}
