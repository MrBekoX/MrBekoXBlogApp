import { Metadata } from 'next';
import { notFound } from 'next/navigation';
import Link from 'next/link';
import { format } from 'date-fns';
import { fetchPostBySlug } from '@/lib/server-api';
import { getImageUrl } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Calendar, Eye, ArrowLeft, Tag, Clock, Sparkles } from 'lucide-react';
import { MarkdownRenderer } from '@/components/markdown-renderer';
import { CommentsSection } from '@/components/comments/comments-section';
import { BlogPostingSchema } from '@/components/seo/blog-posting-schema';
import { BreadcrumbSchema } from '@/components/seo/breadcrumb-schema';
import { ArticleChatPanel } from '@/components/chat';

function sanitizeText(text: string): string {
  return text.replace(/<[^>]*>/g, '').replace(/[<>"'&]/g, (char) => {
    const entities: Record<string, string> = { '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '&': '&amp;' };
    return entities[char] || char;
  });
}

interface PostPageProps {
  params: Promise<{ slug: string }>;
}

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'https://mrbekox.dev';

export async function generateMetadata({ params }: PostPageProps): Promise<Metadata> {
  const { slug } = await params;
  const post = await fetchPostBySlug(slug);

  if (!post) {
    return {
      title: 'Yazı Bulunamadı',
      description: 'Aradığınız yazı mevcut değil.',
    };
  }

  const description = post.excerpt || post.content.substring(0, 160);
  const imageUrl = post.featuredImageUrl ? getImageUrl(post.featuredImageUrl) : undefined;

  return {
    title: post.title,
    description,
    authors: post.author ? [{ name: post.author.fullName || post.author.userName }] : undefined,
    openGraph: {
      title: post.title,
      description,
      type: 'article',
      url: `${SITE_URL}/posts/${slug}`,
      publishedTime: post.publishedAt || post.createdAt,
      modifiedTime: post.updatedAt || post.createdAt,
      authors: post.author ? [post.author.fullName || post.author.userName] : undefined,
      images: imageUrl ? [{ url: imageUrl, alt: post.title }] : undefined,
      tags: post.tags?.map((tag) => tag.name),
    },
    twitter: {
      card: 'summary_large_image',
      title: post.title,
      description,
      images: imageUrl ? [imageUrl] : undefined,
    },
    alternates: {
      canonical: `${SITE_URL}/posts/${slug}`,
    },
  };
}

export default async function PostPage({ params }: PostPageProps) {
  const { slug } = await params;
  const post = await fetchPostBySlug(slug);

  if (!post) {
    notFound();
  }

  return (
    <article className="max-w-3xl font-mono">
      {/* Back link */}
      <Link
        href="/posts"
        className="inline-flex items-center gap-2 text-xs text-gray-500 hover:text-ide-primary transition-colors mb-8"
      >
        <ArrowLeft className="w-3 h-3" />
        <span>cd ../posts/</span>
      </Link>

      {/* Post header */}
      <header className="mb-8 space-y-4">
        {/* Categories */}
        {post.categories && post.categories.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {post.categories.map((category) => (
              <Link key={category.id} href={`/posts?categoryId=${category.id}`}>
                <Badge
                  variant="outline"
                  className="text-[10px] border-ide-border text-gray-500 hover:border-ide-primary hover:text-ide-primary transition-colors"
                >
                  {category.name}
                </Badge>
              </Link>
            ))}
          </div>
        )}

        {/* Title */}
        <h1
          className="text-3xl md:text-4xl text-white glow-text uppercase tracking-tight leading-tight"
          style={{ fontFamily: "'VT323', monospace" }}
        >
          {post.title}
        </h1>

        {/* Meta info */}
        <div className="flex flex-wrap items-center gap-4 text-xs text-gray-500">
          {post.author && (
            <span className="text-gray-400">
              <span className="text-gray-600">@</span>
              {post.author.userName}-MrBekoX
            </span>
          )}
          <span className="flex items-center gap-1">
            <Calendar className="w-3 h-3" />
            {format(new Date(post.publishedAt || post.createdAt), 'MMM d, yyyy')}
          </span>
          <span className="flex items-center gap-1">
            <Eye className="w-3 h-3" />
            {post.viewCount} görüntüleme
          </span>
          {post.aiEstimatedReadingTime && (
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {post.aiEstimatedReadingTime} dk okuma
            </span>
          )}
        </div>
      </header>

      {/* AI Summary */}
      {post.aiSummary && (
        <div className="mb-8 rounded border border-ide-border bg-ide-sidebar p-4">
          <div className="flex items-center gap-2 mb-2">
            <Sparkles className="w-3.5 h-3.5 text-ide-primary" />
            <span className="text-[10px] font-bold uppercase tracking-widest text-ide-primary">
              AI Summary
            </span>
          </div>
          <p className="text-sm text-gray-400 leading-relaxed">
            {sanitizeText(post.aiSummary)}
          </p>
        </div>
      )}

      {/* Featured image */}
      {post.featuredImageUrl && (
        <div className="mb-8 overflow-hidden rounded border border-ide-border">
          <img
            src={getImageUrl(post.featuredImageUrl)}
            alt={post.title}
            className="w-full object-cover"
          />
        </div>
      )}

      <Separator className="my-6 bg-ide-border" />

      {/* Markdown content — MarkdownRenderer handles its own dark prose styling */}
      <MarkdownRenderer content={post.content} author="" />

      {/* Tags */}
      {post.tags && post.tags.length > 0 && (
        <>
          <Separator className="my-8 bg-ide-border" />
          <div className="flex flex-wrap items-center gap-2">
            <Tag className="w-3.5 h-3.5 text-gray-500" />
            {post.tags.map((tag) => (
              <Link key={tag.id} href={`/posts?tagId=${tag.id}`}>
                <Badge
                  variant="outline"
                  className="text-[10px] border-ide-border text-gray-500 hover:border-ide-primary hover:text-ide-primary transition-colors cursor-pointer"
                >
                  #{tag.name}
                </Badge>
              </Link>
            ))}
          </div>
        </>
      )}

      {/* Comments */}
      <Separator className="my-10 bg-ide-border" />
      {post.id && <CommentsSection postId={post.id} />}

      {/* Schema.org */}
      <BlogPostingSchema
        title={post.title}
        description={post.excerpt || post.content.substring(0, 200)}
        slug={slug}
        publishedAt={post.publishedAt || post.createdAt}
        updatedAt={post.updatedAt || post.createdAt}
        featuredImageUrl={post.featuredImageUrl}
        author={post.author}
        tags={post.tags}
        categories={post.categories}
      />
      <BreadcrumbSchema
        items={[
          { name: 'Ana Sayfa', url: '/' },
          { name: 'Yazılar', url: '/posts' },
          { name: post.title, url: `/posts/${slug}` },
        ]}
      />

      {/* AI Chat Panel */}
      <ArticleChatPanel postId={post.id} postTitle={post.title} />
    </article>
  );
}
