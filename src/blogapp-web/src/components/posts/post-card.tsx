import Link from 'next/link';
import { format } from 'date-fns';
import { tr } from 'date-fns/locale';
import { getImageUrl } from '@/lib/utils';
import type { BlogPost } from '@/types';
import { Calendar, Eye, Clock, FileText, Tag } from 'lucide-react';

interface PostCardProps {
  post: BlogPost;
}

export function PostCard({ post }: PostCardProps) {
  return (
    <Link
      href={`/posts/${post.slug}`}
      className="group flex items-start gap-3 py-4 px-3 border-b border-ide-border/40 hover:border-ide-border hover:bg-white/[0.03] transition-all font-mono"
    >
      {/* File icon */}
      <FileText className="w-4 h-4 text-yellow-500 shrink-0 mt-0.5" />

      <div className="min-w-0 flex-1 space-y-1.5">
        {/* Filename + date row */}
        <div className="flex items-center justify-between gap-4">
          <span className="text-[11px] text-gray-500 truncate">
            {post.slug}.md
          </span>
          <span className="text-[10px] text-gray-600 shrink-0 flex items-center gap-1">
            <Calendar className="w-2.5 h-2.5" />
            {format(new Date(post.publishedAt || post.createdAt), 'd MMM yyyy', { locale: tr })}
          </span>
        </div>

        {/* Title */}
        <div className="text-sm text-gray-200 group-hover:text-white transition-colors leading-snug line-clamp-1">
          {post.title}
        </div>

        {/* Excerpt */}
        {post.excerpt && (
          <p className="text-[11px] text-gray-600 leading-relaxed line-clamp-2">
            {post.excerpt}
          </p>
        )}

        {/* Meta row */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-0.5">
          {post.author && (
            <span className="text-[10px] text-gray-600">
              @{post.author.userName}-MrBekoX
            </span>
          )}
          {post.aiEstimatedReadingTime && (
            <span className="text-[10px] text-gray-600 flex items-center gap-1">
              <Clock className="w-2.5 h-2.5" />
              {post.aiEstimatedReadingTime}dk
            </span>
          )}
          <span className="text-[10px] text-gray-600 flex items-center gap-1">
            <Eye className="w-2.5 h-2.5" />
            {post.viewCount}
          </span>
          {post.tags?.slice(0, 3).map((tag) => (
            <span key={tag.id} className="text-[10px] text-ide-primary-dim flex items-center gap-0.5">
              <Tag className="w-2 h-2" />
              {tag.name}
            </span>
          ))}
          {post.categories?.slice(0, 1).map((cat) => (
            <span key={cat.id} className="text-[10px] text-gray-600 border border-ide-border/60 px-1.5 py-0.5 rounded">
              {cat.name}
            </span>
          ))}
        </div>
      </div>
    </Link>
  );
}
