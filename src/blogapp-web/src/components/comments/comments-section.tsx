'use client';

import * as React from 'react';
import { useAuthStore } from '@/stores/auth-store';
import { commentsApi } from '@/lib/api';
import { CommentForm } from './comment-form';
import { CommentCard } from './comment-card';
import { Skeleton } from '@/components/ui/skeleton';
import { MessageSquare } from 'lucide-react';
import type { Comment } from '@/types';

interface CommentsSectionProps {
  postId: string;
}

export function CommentsSection({ postId }: CommentsSectionProps) {
  const { isAuthenticated, user } = useAuthStore();
  const [comments, setComments] = React.useState<Comment[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [isAvailable, setIsAvailable] = React.useState(true);

  const fetchComments = React.useCallback(async () => {
    try {
      const response = await commentsApi.getByPostId(postId);
      if (response.success && response.data) {
        setComments(response.data);
      }
    } catch {
      // Comments API not available yet - silently handle
      setIsAvailable(false);
    } finally {
      setIsLoading(false);
    }
  }, [postId]);

  React.useEffect(() => {
    fetchComments();
  }, [fetchComments]);

  const handleCommentAdded = (newComment: Comment) => {
    setComments((prev) => [newComment, ...prev]);
  };

  const handleReplyAdded = (parentId: string, reply: Comment) => {
    setComments((prev) =>
      prev.map((comment) => {
        if (comment.id === parentId) {
          return {
            ...comment,
            replies: [...(comment.replies || []), reply],
          };
        }
        return comment;
      })
    );
  };

  // Filter to show only approved comments for non-authenticated users
  // or all comments for the author
  const visibleComments = comments.filter(
    (c) => c.isApproved || (user && c.authorName === user.fullName)
  );

  return (
    <section className="space-y-8">
      <div className="flex items-center gap-2">
        <MessageSquare className="h-6 w-6" />
        <h2 className="text-2xl font-bold">
          Comments {visibleComments.length > 0 && `(${visibleComments.length})`}
        </h2>
      </div>

      {/* Comment Form */}
      {isAvailable && (
        <CommentForm
          postId={postId}
          onCommentAdded={handleCommentAdded}
          isAuthenticated={isAuthenticated}
          user={user}
        />
      )}

      {/* Comments List */}
      <div className="space-y-6">
        {isLoading ? (
          Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="space-y-3">
              <div className="flex items-center gap-3">
                <Skeleton className="h-10 w-10 rounded-full" />
                <div className="space-y-1">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-3 w-24" />
                </div>
              </div>
              <Skeleton className="h-16 w-full" />
            </div>
          ))
        ) : !isAvailable ? (
          <div className="py-12 text-center">
            <MessageSquare className="mx-auto h-12 w-12 text-muted-foreground/50" />
            <p className="mt-4 text-muted-foreground">
              Yorumlar şu an için kullanılamıyor.
            </p>
          </div>
        ) : visibleComments.length > 0 ? (
          visibleComments.map((comment) => (
            <CommentCard
              key={comment.id}
              comment={comment}
              postId={postId}
              onReplyAdded={handleReplyAdded}
              isAuthenticated={isAuthenticated}
              user={user}
            />
          ))
        ) : (
          <div className="py-12 text-center">
            <MessageSquare className="mx-auto h-12 w-12 text-muted-foreground/50" />
            <p className="mt-4 text-muted-foreground">
              Henüz yorum yok. İlk yorumu siz yapın!
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

