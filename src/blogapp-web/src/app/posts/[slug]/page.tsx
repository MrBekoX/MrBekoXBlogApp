'use client';

import { useEffect, use } from 'react';
import type { Metadata } from 'next';
import Link from 'next/link';
import { format } from 'date-fns';
import { usePostsStore } from '@/stores/posts-store';
import { postsApi } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Skeleton } from '@/components/ui/skeleton';
import { Calendar, Eye, ArrowLeft, Tag } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { MarkdownRenderer } from '@/components/markdown-renderer';
import { CommentsSection } from '@/components/comments/comments-section';
import { BlogPostingSchema } from '@/components/seo/blog-posting-schema';
import { BreadcrumbSchema } from '@/components/seo/breadcrumb-schema';

interface PostPageProps {
  params: Promise<{ slug: string }>;
}

export default function PostPage({ params }: PostPageProps) {
  const { slug } = use(params);
  const { currentPost, isLoading, fetchPostBySlug, clearCurrentPost } = usePostsStore();

  useEffect(() => {
    fetchPostBySlug(slug);
    return () => clearCurrentPost();
  }, [slug, fetchPostBySlug, clearCurrentPost]);

  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map((n) => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  if (isLoading) {
    return (
      <div className="container max-w-4xl py-12">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="mt-8 h-12 w-3/4" />
        <div className="mt-4 flex gap-2">
          <Skeleton className="h-6 w-20" />
          <Skeleton className="h-6 w-20" />
        </div>
        <Skeleton className="mt-8 aspect-video w-full" />
        <div className="mt-8 space-y-4">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      </div>
    );
  }

  if (!currentPost) {
    return (
      <div className="container max-w-4xl py-12 text-center">
        <h1 className="text-2xl font-bold">Post not found</h1>
        <p className="mt-2 text-muted-foreground">The post you&apos;re looking for doesn&apos;t exist.</p>
        <Button asChild className="mt-4">
          <Link href="/posts">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to posts
          </Link>
        </Button>
      </div>
    );
  }

  return (
    <article className="container max-w-4xl py-12">
      <Button asChild variant="ghost" className="mb-8">
        <Link href="/posts">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to posts
        </Link>
      </Button>

      <header className="space-y-4">
        {currentPost.categories && currentPost.categories.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {currentPost.categories.map((category) => (
              <Link key={category.id} href={`/categories/${category.slug}`}>
                <Badge variant="secondary" className="hover:bg-secondary/80">
                  {category.name}
                </Badge>
              </Link>
            ))}
          </div>
        )}

        <h1 className="text-4xl font-bold tracking-tight">{currentPost.title}</h1>

        <div className="flex flex-wrap items-center gap-6 text-muted-foreground">
          {currentPost.author && (
            <div className="flex items-center gap-2">
              <Avatar className="h-10 w-10">
                <AvatarImage src={currentPost.author.avatarUrl} alt={currentPost.author.fullName} />
                <AvatarFallback>
                  {getInitials(currentPost.author.fullName || currentPost.author.userName)}
                </AvatarFallback>
              </Avatar>
              <div>
                <p className="font-medium text-foreground">
                  {currentPost.author.fullName || currentPost.author.userName}
                </p>
              </div>
            </div>
          )}

          <div className="flex items-center gap-1">
            <Calendar className="h-4 w-4" />
            <span>
              {format(new Date(currentPost.publishedAt || currentPost.createdAt), 'MMMM d, yyyy')}
            </span>
          </div>

          <div className="flex items-center gap-1">
            <Eye className="h-4 w-4" />
            <span>{currentPost.viewCount} views</span>
          </div>
        </div>
      </header>

      {currentPost.featuredImageUrl && (
        <div className="mt-8 overflow-hidden rounded-lg">
          <img
            src={currentPost.featuredImageUrl}
            alt={currentPost.title}
            className="w-full object-cover"
          />
        </div>
      )}

      <Separator className="my-8" />

      <MarkdownRenderer content={currentPost.content} />

      {currentPost.tags && currentPost.tags.length > 0 && (
        <>
          <Separator className="my-8" />
          <div className="flex flex-wrap items-center gap-2">
            <Tag className="h-4 w-4 text-muted-foreground" />
            {currentPost.tags.map((tag) => (
              <Link key={tag.id} href={`/tags/${tag.slug}`}>
                <Badge variant="outline" className="hover:bg-accent">
                  #{tag.name}
                </Badge>
              </Link>
            ))}
          </div>
        </>
      )}

      {/* Comments Section */}
      <Separator className="my-12" />
      <CommentsSection postId={currentPost.id} />

      {/* Schema.org Structured Data */}
      <BlogPostingSchema
        title={currentPost.title}
        description={currentPost.excerpt || currentPost.content.substring(0, 200)}
        slug={slug}
        publishedAt={currentPost.publishedAt || currentPost.createdAt}
        updatedAt={currentPost.updatedAt || currentPost.createdAt}
        featuredImageUrl={currentPost.featuredImageUrl}
        author={currentPost.author}
        tags={currentPost.tags}
        categories={currentPost.categories}
      />
      <BreadcrumbSchema
        items={[
          { name: 'Ana Sayfa', url: '/' },
          { name: 'Yazılar', url: '/posts' },
          { name: currentPost.title, url: `/posts/${slug}` },
        ]}
      />
    </article>
  );
}
