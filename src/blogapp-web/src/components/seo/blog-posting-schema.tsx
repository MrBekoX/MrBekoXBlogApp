import { BlogPosting, Person, WithContext } from 'schema-dts';
import { JsonLd } from './json-ld';

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'https://mrbekox.dev';

interface BlogPostingSchemaProps {
  title: string;
  description: string;
  slug: string;
  publishedAt: string;
  updatedAt: string;
  featuredImageUrl?: string;
  author: {
    fullName: string;
    userName: string;
    avatarUrl?: string;
  };
  tags?: { name: string }[];
  categories?: { name: string }[];
}

export function BlogPostingSchema({
  title,
  description,
  slug,
  publishedAt,
  updatedAt,
  featuredImageUrl,
  author,
  tags,
  categories,
}: BlogPostingSchemaProps) {
  const authorSchema: Person = {
    '@type': 'Person',
    name: author.fullName || author.userName,
    url: SITE_URL,
    ...(author.avatarUrl && { image: author.avatarUrl }),
  };

  const blogPostingSchema: WithContext<BlogPosting> = {
    '@context': 'https://schema.org',
    '@type': 'BlogPosting',
    headline: title,
    description: description,
    url: `${SITE_URL}/posts/${slug}`,
    datePublished: publishedAt,
    dateModified: updatedAt,
    author: authorSchema,
    publisher: {
      '@type': 'Organization',
      name: 'MrBekoX',
      url: SITE_URL,
      logo: {
        '@type': 'ImageObject',
        url: `${SITE_URL}/images/avatar.jpg`,
      },
    },
    ...(featuredImageUrl && {
      image: {
        '@type': 'ImageObject',
        url: featuredImageUrl,
      },
    }),
    ...(tags && tags.length > 0 && {
      keywords: tags.map((tag) => tag.name).join(', '),
    }),
    ...(categories && categories.length > 0 && {
      articleSection: categories.map((cat) => cat.name),
    }),
    inLanguage: 'tr-TR',
    mainEntityOfPage: {
      '@type': 'WebPage',
      '@id': `${SITE_URL}/posts/${slug}`,
    },
  };

  return <JsonLd data={blogPostingSchema} />;
}
