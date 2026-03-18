'use client';

import * as React from 'react';
import { format, formatDistanceToNow } from 'date-fns';
import { MessageSquare, Clock, CornerDownRight, Circle } from 'lucide-react';
import { CommentForm } from './comment-form';
import type { Comment, User } from '@/types';

interface CommentCardProps {
  comment: Comment;
  postId: string;
  onReplyAdded: (parentId: string, reply: Comment) => void;
  isAuthenticated: boolean;
  user: User | null;
  isReply?: boolean;
}

export function CommentCard({
  comment,
  postId,
  onReplyAdded,
  isAuthenticated,
  user,
  isReply = false,
}: CommentCardProps) {
  const [showReplyForm, setShowReplyForm] = React.useState(false);

  const handleReplyAdded = (reply: Comment) => {
    onReplyAdded(comment.id, reply);
    setShowReplyForm(false);
  };

  const timeAgo = formatDistanceToNow(new Date(comment.createdAt), { addSuffix: true });

  return (
    <div className={`font-mono ${isReply ? 'ml-6 pl-4 border-l-2 border-ide-border/40' : ''}`}>
      {/* Comment entry */}
      <div className="py-3 border-b border-ide-border/30">
        {/* Header line */}
        <div className="flex flex-wrap items-center gap-2 text-xs mb-2">
          <Circle className="w-2 h-2 fill-ide-primary/60 text-ide-primary/60" />
          <span className="text-ide-primary">{comment.authorName}</span>
          {!comment.isApproved && (
            <span className="text-[10px] text-yellow-500 border border-yellow-500/30 px-1.5 py-0.5 rounded">
              pending
            </span>
          )}
          <span className="flex items-center gap-1 text-gray-600">
            <Clock className="w-2.5 h-2.5" />
            <time
              dateTime={comment.createdAt}
              title={format(new Date(comment.createdAt), 'PPpp')}
            >
              {timeAgo}
            </time>
          </span>
        </div>

        {/* Comment content */}
        <div className="pl-4">
          <p className="text-sm text-gray-400 leading-relaxed whitespace-pre-wrap">
            <span className="text-gray-600 mr-2">&gt;</span>
            {comment.content}
          </p>

          {/* Reply button */}
          {!isReply && (
            <button
              className="mt-2 flex items-center gap-1 text-[10px] text-gray-500 hover:text-ide-primary transition-colors"
              onClick={() => setShowReplyForm(!showReplyForm)}
            >
              <CornerDownRight className="w-3 h-3" />
              <span>{showReplyForm ? 'iptal' : 'yanıtla'}</span>
            </button>
          )}
        </div>
      </div>

      {/* Reply Form */}
      {showReplyForm && (
        <div className="ml-4 mt-3">
          <CommentForm
            postId={postId}
            parentCommentId={comment.id}
            onCommentAdded={handleReplyAdded}
            onCancel={() => setShowReplyForm(false)}
            isAuthenticated={isAuthenticated}
            user={user}
            isReply
          />
        </div>
      )}

      {/* Nested Replies */}
      {comment.replies && comment.replies.length > 0 && (
        <div className="mt-1">
          {comment.replies.map((reply) => (
            <CommentCard
              key={reply.id}
              comment={reply}
              postId={postId}
              onReplyAdded={onReplyAdded}
              isAuthenticated={isAuthenticated}
              user={user}
              isReply
            />
          ))}
        </div>
      )}
    </div>
  );
}
