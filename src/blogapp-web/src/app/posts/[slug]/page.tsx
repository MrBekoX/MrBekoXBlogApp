import { Metadata } from 'next';
import { notFound } from 'next/navigation';
import Link from 'next/link';
import { format } from 'date-fns';
import { fetchPostBySlug } from '@/lib/server-api';
import { getImageUrl } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Calendar, Eye, ArrowLeft, Tag, Clock, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
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

/**
 * Generate dynamic metadata for SEO
 */
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
      images: imageUrl ? [
        {
          url: imageUrl,
          alt: post.title,
        }
      ] : undefined,
      tags: post.tags?.map(tag => tag.name),
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

function getInitials(name: string): string {
  return name
    .split(' ')
    .map((n) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);
}

export default async function PostPage({ params }: PostPageProps) {
  const { slug } = await params;
  const post = await fetchPostBySlug(slug);

  if (!post) {
    notFound();
  }

  return (
    <article className="container max-w-4xl py-12">
      <Button asChild variant="ghost" className="mb-8">
        <Link href="/posts">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Yazılara Dön
        </Link>
      </Button>

      <header className="space-y-4">
        {post.categories && post.categories.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {post.categories.map((category) => (
              <Link key={category.id} href={`/posts?categoryId=${category.id}`}>
                <Badge variant="secondary" className="cursor-pointer hover:bg-secondary/80 transition-colors">
                  {category.name}
                </Badge>
              </Link>
            ))}
          </div>
        )}
        
        {/* Single category display as fallback */}
        {post.category && (!post.categories || post.categories.length === 0) && (
          <Link href={`/posts?categoryId=${post.category.id}`}>
            <Badge variant="secondary" className="cursor-pointer hover:bg-secondary/80 transition-colors">
              {post.category.name}
            </Badge>
          </Link>
        )}

        <h1 className="text-4xl font-bold tracking-tight">{post.title}</h1>

        <div className="flex flex-wrap items-center gap-6 text-muted-foreground">
          {post.author && (
            <div className="flex items-center gap-2">
              <Avatar className="h-10 w-10">
                <AvatarImage src={post.author.avatarUrl} alt={post.author.fullName} />
                <AvatarFallback>
                  {getInitials(post.author.fullName || post.author.userName)}
                </AvatarFallback>
              </Avatar>
              <div>
                <p className="font-medium text-foreground">
                  {post.author.fullName || post.author.userName}
                </p>
              </div>
            </div>
          )}

          <div className="flex items-center gap-1">
            <Calendar className="h-4 w-4" />
            <span>
              {format(new Date(post.publishedAt || post.createdAt), 'MMMM d, yyyy')}
            </span>
          </div>

          <div className="flex items-center gap-1">
            <Eye className="h-4 w-4" />
            <span>{post.viewCount} görüntüleme</span>
          </div>

          {post.aiEstimatedReadingTime && (
            <div className="flex items-center gap-1">
              <Clock className="h-4 w-4" />
              <span>{post.aiEstimatedReadingTime} dk okuma</span>
            </div>
          )}
        </div>
      </header>

      {/* AI Summary Section */}
      {post.aiSummary && (
        <div className="mt-8 rounded-lg border border-primary/20 bg-primary/5 p-6">
          <div className="flex items-center gap-2 mb-3">
            <Sparkles className="h-5 w-5 text-primary" />
            <span className="font-semibold text-primary">AI Tarafindan Olusturulan Ozet</span>
          </div>
          <p className="text-muted-foreground leading-relaxed">
            {sanitizeText(post.aiSummary)}
          </p>
        </div>
      )}

      {/* AI Agent Dropdown - Always show for AI tools */}
      {/* AI Agent Dropdown removed as per user request */}

      {post.featuredImageUrl && (
        <div className="mt-8 overflow-hidden rounded-lg">
          <img
            src={getImageUrl(post.featuredImageUrl)}
            alt={post.title}
            className="w-full object-cover"
          />
        </div>
      )}

      <Separator className="my-8" />

      <MarkdownRenderer content={post.content} />

      {post.tags && post.tags.length > 0 && (
        <>
          <Separator className="my-8" />
          <div className="flex flex-wrap items-center gap-2">
            <Tag className="h-4 w-4 text-muted-foreground" />
            {post.tags.map((tag) => (
              <Link key={tag.id} href={`/posts?tagId=${tag.id}`}>
                <Badge variant="outline" className="cursor-pointer hover:bg-accent transition-colors">
                  #{tag.name}
                </Badge>
              </Link>
            ))}
          </div>
        </>
      )}

      {/* Comments Section - Client Component */}
      <Separator className="my-12" />
      <CommentsSection postId={post.id} />

      {/* Schema.org Structured Data */}
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

      {/* Article Chat Panel */}
      <ArticleChatPanel postId={post.id} postTitle={post.title} />
    </article>
  );
}
