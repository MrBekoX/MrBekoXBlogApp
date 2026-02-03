import { Thing, WithContext } from 'schema-dts';

interface JsonLdProps {
  data: WithContext<Thing> | WithContext<Thing>[];
}

/**
 * Component for embedding JSON-LD structured data in the document head.
 * Supports single schema or array of schemas.
 * 
 * Note: JSON.stringify handles all necessary escaping for JSON content.
 * HTML escaping would break the JSON structure (e.g., " becomes &quot;).
 * The script tag with type="application/ld+json" is not executed as JavaScript,
 * so XSS through JSON-LD is not a concern.
 */
export function JsonLd({ data }: JsonLdProps) {
  const jsonString = JSON.stringify(data, null, 0);
  
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{
        __html: jsonString,
      }}
    />
  );
}
