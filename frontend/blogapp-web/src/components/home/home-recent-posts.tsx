'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePostsStore } from '@/stores/posts-store';
import { postsApi } from '@/lib/api';
import { format } from 'date-fns';
import { Calendar, Eye, FileText, Tag } from 'lucide-react';
import type { BlogPost } from '@/types';

interface HomeRecentPostsProps {
  initialPosts: BlogPost[];
}

/**
 * Client component for homepage recent posts.
 * Uses server data initially, then directly fetches fresh data
 * when cache is invalidated via SignalR.
 */
export function HomeRecentPosts({ initialPosts }: HomeRecentPostsProps) {
  const cacheVersion = usePostsStore((state) => state.cacheVersion);
  const [posts, setPosts] = useState(initialPosts);
  const prevVersion = useRef(cacheVersion);

  useEffect(() => {
    if (prevVersion.current === cacheVersion) return;
    prevVersion.current = cacheVersion;

    postsApi.getAll({
      pageSize: 5,
      status: 'Published',
      sortBy: 'publishedat',
      sortDescending: true,
    })
      .then(response => {
        if (response.success && response.data?.items) {
          setPosts(response.data.items);
        }
      })
      .catch(() => {});
  }, [cacheVersion]);

  if (posts.length === 0) return null;

  return (
    <div>
      <div className="border-b border-ide-border/50 mb-4 pb-2">
        <span className="text-[10px] font-bold uppercase tracking-widest text-gray-500">
          // Recent Entries
        </span>
      </div>

      <div className="space-y-4">
        {posts.map((post) => (
          <Link
            key={post.id}
            href={`/posts/${post.slug}`}
            className="group flex items-start gap-3 p-3 rounded border border-ide-border/30 hover:border-ide-border hover:bg-white/5 transition-all"
          >
            <FileText className="w-4 h-4 text-ide-primary mt-0.5 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="text-sm text-gray-200 group-hover:text-white transition-colors truncate">
                {post.title}
              </div>
              <div className="flex flex-wrap items-center gap-3 mt-1 text-[10px] text-gray-600">
                {post.publishedAt && (
                  <span className="flex items-center gap-1">
                    <Calendar className="w-2.5 h-2.5" />
                    {format(new Date(post.publishedAt), 'MMM d, yyyy')}
                  </span>
                )}
                <span className="flex items-center gap-1">
                  <Eye className="w-2.5 h-2.5" />
                  {post.viewCount}
                </span>
                {post.tags?.slice(0, 2).map((tag) => (
                  <span key={tag.id} className="flex items-center gap-1 text-ide-primary-dim">
                    <Tag className="w-2.5 h-2.5" />
                    {tag.name}
                  </span>
                ))}
              </div>
            </div>
          </Link>
        ))}
      </div>

      <div className="mt-6">
        <Link
          href="/posts"
          className="inline-flex items-center gap-2 text-xs text-ide-primary hover:text-white border border-ide-primary/30 hover:border-ide-primary px-4 py-2 rounded transition-all"
        >
          <span>ls -la /posts/</span>
          <span className="text-gray-500">→ tüm yazıları gör</span>
        </Link>
      </div>
    </div>
  );
}
