import Link from 'next/link';
import { fetchPosts, fetchTags } from '@/lib/server-api';
import { format } from 'date-fns';
import { Calendar, Clock, Eye, FileText, Tag } from 'lucide-react';

export default async function HomePage() {
  const [postsData, tagsData] = await Promise.all([
    fetchPosts({ pageSize: 5, status: 'Published', sortBy: 'publishedat', sortDescending: true }),
    fetchTags(),
  ]);

  const posts = postsData?.items || [];
  const tags = tagsData || [];

  return (
    <div className="max-w-3xl font-mono">
      {/* ── Greeting ─────────────────────────────────────────── */}
      <div className="mb-12">
        <h1
          className="text-4xl md:text-5xl text-white mb-4 glow-text uppercase tracking-tight leading-tight"
          style={{ fontFamily: "'VT323', monospace" }}
        >
          Merhaba, ben{' '}
          <span className="text-ide-primary">MrBekoX</span>
        </h1>

        <div className="text-sm text-ide-primary-dim mb-8">
          {tags
            .slice(0, 3)
            .map((t) => `#${t.name}`)
            .join(' ')}
        </div>

      </div>

      {/* ── Recent posts ─────────────────────────────────────── */}
      {posts.length > 0 && (
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
      )}
    </div>
  );
}
