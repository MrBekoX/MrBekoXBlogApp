'use client';

import { MessageSquare, Clock, Terminal } from 'lucide-react';

interface CommentsSectionProps {
  postId: string;
}

// Temporarily disabled until backend Comments API is implemented
export function CommentsSection({ postId }: CommentsSectionProps) {
  return (
    <section className="space-y-4 font-mono">
      {/* Terminal header */}
      <div className="border-b border-ide-border/50 pb-2 mb-4">
        <div className="flex items-center gap-2 text-[10px] text-gray-500 uppercase tracking-widest">
          <Terminal className="w-3 h-3 text-ide-primary" />
          <span>// comments.sh</span>
        </div>
      </div>

      {/* Title */}
      <div className="flex items-center gap-2 mb-6">
        <MessageSquare className="w-4 h-4 text-ide-primary" />
        <h2 className="text-sm text-gray-300">Yorumlar</h2>
        <span className="text-xs text-gray-600">({postId.slice(0, 8)}...)</span>
      </div>

      {/* Coming soon terminal box */}
      <div className="bg-ide-sidebar border border-ide-border/50 rounded p-4">
        <div className="flex items-center gap-2 text-green-400 mb-3 text-xs">
          <span className="text-green-400">●</span>
          <span>status.sh</span>
        </div>
        <div className="text-sm space-y-1.5 text-gray-400">
          <div>
            <span className="text-gray-600">➜ </span>
            <span className="text-white">comments --status</span>
          </div>
          <div className="pl-4 flex items-center gap-2">
            <Clock className="w-3 h-3 text-ide-primary animate-pulse" />
            <span>Yorum sistemi yakında aktif olacak...</span>
            <span className="cursor-blink bg-ide-primary w-2 h-4 inline-block align-middle" />
          </div>
        </div>
      </div>

      {/* Info text */}
      <div className="text-xs text-gray-600 pl-1 mt-4">
        <span className="text-gray-600"># </span>
        Yorumlarınızı paylaşmak için kısa süre içinde bu alanı kullanabileceksiniz.
      </div>
    </section>
  );
}
