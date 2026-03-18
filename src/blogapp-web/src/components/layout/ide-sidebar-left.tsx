import Link from 'next/link';
import { fetchPosts } from '@/lib/server-api';
import { FileText, Lock, ExternalLink } from 'lucide-react';
import { IdeUserFooter } from './ide-user-footer';

function PostIcon({ index }: { index: number }) {
  if (index === 0) return <ExternalLink className="w-3 h-3 text-blue-400 shrink-0" />;
  if (index % 5 === 3) return <Lock className="w-3 h-3 text-red-400 shrink-0" />;
  return <FileText className="w-3 h-3 text-yellow-500 shrink-0" />;
}

export async function IdeSidebarLeft() {
  const postsData = await fetchPosts({
    pageSize: 8,
    status: 'Published',
    sortBy: 'publishedat',
    sortDescending: true,
  });
  const posts = postsData?.items || [];

  return (
    <aside className="w-64 bg-ide-sidebar border-r border-ide-border flex flex-col shrink-0 h-full">
      {/* Explorer header */}
      <div className="p-3 uppercase text-[10px] font-bold tracking-widest text-gray-500 border-b border-ide-border/50 font-mono">
        Explorer
      </div>

      {/* File tree */}
      <div className="flex-1 overflow-y-auto ide-scrollbar py-2">
        <div>
          {/* Folder label */}
          <div className="flex items-center px-4 py-1 text-xs text-gray-300 font-mono">
            <span className="mr-2 text-[10px]">▾</span>
            <span className="font-bold uppercase tracking-tighter">Blog_Logs</span>
          </div>

          {/* Home link */}
          <div className="pl-4 mt-1 space-y-0.5">
            <Link
              href="/"
              className="flex items-center py-1 px-4 text-xs text-gray-400 hover:text-white hover:bg-white/5 transition-colors font-mono"
            >
              <FileText className="w-3 h-3 text-yellow-500 mr-2 shrink-0" />
              <span className="truncate">how-to-center.md</span>
            </Link>

            {/* Post links */}
            {posts.map((post, index) => (
              <Link
                key={post.id}
                href={`/posts/${post.slug}`}
                className="flex items-center py-1 px-4 text-xs text-gray-400 hover:text-white hover:bg-white/5 transition-colors font-mono"
              >
                <PostIcon index={index} />
                <span className="truncate ml-2">
                  {post.slug.length > 22 ? post.slug.substring(0, 22) + '…' : post.slug}.md
                </span>
              </Link>
            ))}
          </div>
        </div>
      </div>

      {/* User status footer — auth-aware client component */}
      <IdeUserFooter />
    </aside>
  );
}
