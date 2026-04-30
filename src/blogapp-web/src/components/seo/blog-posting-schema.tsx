import { BlogPosting, WithContext } from 'schema-dts';
import { JsonLd } from './json-ld';
import { getImageUrl } from '@/lib/utils';
import {
  SITE_URL,
  SITE_NAME,
  SOCIAL_URLS,
} from '@/lib/site-config';
import { resolveEntities } from '@/lib/geo-entities';

interface BlogPostingSchemaProps {
  title: string;
  description: string;
  slug: string;
  content: string;
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

function countWords(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

function stripMarkdown(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, '')       // code blocks
    .replace(/`[^`]+`/g, '')              // inline code
    .replace(/!\[.*?\]\(.*?\)/g, '')      // images
    .replace(/\[(.+?)\]\(.*?\)/g, '$1')   // links → text only
    .replace(/#{1,6}\s+/g, '')            // headings
    .replace(/[*_~]+/g, '')               // bold/italic/strikethrough
    .replace(/>\s+/g, '')                 // blockquotes
    .replace(/[-*]\s+/g, '')              // list markers
    .replace(/\n{2,}/g, ' ')             // multiple newlines
    .replace(/\n/g, ' ')                 // single newlines
    .trim();
}

export function BlogPostingSchema({
  title,
  description,
  slug,
  content,
  publishedAt,
  updatedAt,
  featuredImageUrl,
  author,
  tags,
  categories,
}: BlogPostingSchemaProps) {
  const wordCount = countWords(content);
  const plainContent = stripMarkdown(content);
  const articleBody = plainContent.length > 500
    ? plainContent.substring(0, 497) + '...'
    : plainContent;

  // Entity linking — tag/kategori isimlerini Thing entity'lerine cevir
  const aboutEntities = resolveEntities(tags, categories);

  const blogPostingSchema: WithContext<BlogPosting> = {
    '@context': 'https://schema.org',
    '@type': 'BlogPosting',
    '@id': `${SITE_URL}/posts/${slug}/#article`,
    headline: title,
    description: description,
    url: `${SITE_URL}/posts/${slug}`,
    datePublished: publishedAt,
    dateModified: updatedAt,
    wordCount: wordCount,
    articleBody: articleBody,
    author: {
      '@type': 'Person',
      '@id': `${SITE_URL}/#author`,
      name: author.fullName || author.userName,
      url: SITE_URL,
      sameAs: SOCIAL_URLS,
      ...(author.avatarUrl && { image: author.avatarUrl }),
    },
    publisher: {
      '@type': 'Organization',
      '@id': `${SITE_URL}/#organization`,
      name: SITE_NAME,
      url: SITE_URL,
      logo: {
        '@type': 'ImageObject',
        url: `${SITE_URL}/images/avatar.jpg`,
      },
    },
    ...(featuredImageUrl && getImageUrl(featuredImageUrl) && {
      image: {
        '@type': 'ImageObject',
        url: getImageUrl(featuredImageUrl)!,
      },
    }),
    ...(tags && tags.length > 0 && {
      keywords: tags.map((tag) => tag.name).join(', '),
    }),
    ...(categories && categories.length > 0 && {
      articleSection: categories.map((cat) => cat.name),
    }),
    ...(aboutEntities.length > 0 && {
      about: aboutEntities,
    }),
    speakable: {
      '@type': 'SpeakableSpecification',
      cssSelector: ['.post-title', '.post-excerpt'],
    },
    inLanguage: 'tr-TR',
    mainEntityOfPage: {
      '@type': 'WebPage',
      '@id': `${SITE_URL}/posts/${slug}`,
    },
  } as WithContext<BlogPosting>;

  return <JsonLd data={blogPostingSchema} />;
}
