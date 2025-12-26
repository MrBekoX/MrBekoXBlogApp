'use client';

import * as React from 'react';
import { format, formatDistanceToNow } from 'date-fns';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { CommentForm } from './comment-form';
import { MessageSquare, Clock } from 'lucide-react';
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

  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map((n) => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  const handleReplyAdded = (reply: Comment) => {
    onReplyAdded(comment.id, reply);
    setShowReplyForm(false);
  };

  const timeAgo = formatDistanceToNow(new Date(comment.createdAt), { addSuffix: true });

  return (
    <div className={`space-y-4 ${isReply ? 'ml-8 pl-4 border-l-2 border-muted' : ''}`}>
      <div className="flex gap-4">
        <Avatar className="h-10 w-10">
          <AvatarFallback className="bg-primary/10 text-primary">
            {getInitials(comment.authorName)}
          </AvatarFallback>
        </Avatar>

        <div className="flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{comment.authorName}</span>
            {!comment.isApproved && (
              <Badge variant="outline" className="text-xs">
                Pending approval
              </Badge>
            )}
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <Clock className="h-3 w-3" />
              <time
                dateTime={comment.createdAt}
                title={format(new Date(comment.createdAt), 'PPpp')}
              >
                {timeAgo}
              </time>
            </span>
          </div>

          <p className="text-sm leading-relaxed whitespace-pre-wrap">
            {comment.content}
          </p>

          {!isReply && (
            <Button
              variant="ghost"
              size="sm"
              className="h-8 px-2 text-muted-foreground hover:text-foreground"
              onClick={() => setShowReplyForm(!showReplyForm)}
            >
              <MessageSquare className="mr-1 h-4 w-4" />
              Reply
            </Button>
          )}
        </div>
      </div>

      {/* Reply Form */}
      {showReplyForm && (
        <div className="ml-14">
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
        <div className="space-y-4">
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

