'use client';

import * as React from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod/v4';
import { commentsApi } from '@/lib/api';
import { toast } from 'sonner';
import { Loader2, Send, X, Terminal, CornerDownRight } from 'lucide-react';
import type { Comment, User } from '@/types';

const guestCommentSchema = z.object({
  content: z.string().min(1, 'Comment is required').max(1000, 'Comment is too long'),
  authorName: z.string().min(1, 'Name is required').max(100),
  authorEmail: z.email('Please enter a valid email'),
});

const authCommentSchema = z.object({
  content: z.string().min(1, 'Comment is required').max(1000, 'Comment is too long'),
});

type GuestFormData = z.infer<typeof guestCommentSchema>;
type AuthFormData = z.infer<typeof authCommentSchema>;

interface CommentFormProps {
  postId: string;
  parentCommentId?: string;
  onCommentAdded: (comment: Comment) => void;
  onCancel?: () => void;
  isAuthenticated: boolean;
  user: User | null;
  isReply?: boolean;
}

export function CommentForm({
  postId,
  parentCommentId,
  onCommentAdded,
  onCancel,
  isAuthenticated,
  user,
  isReply = false,
}: CommentFormProps) {
  const [isSubmitting, setIsSubmitting] = React.useState(false);

  const guestForm = useForm<GuestFormData>({
    resolver: zodResolver(guestCommentSchema),
  });

  const authForm = useForm<AuthFormData>({
    resolver: zodResolver(authCommentSchema),
  });

  const onSubmit = async (data: GuestFormData | AuthFormData) => {
    setIsSubmitting(true);
    try {
      const payload = {
        postId,
        content: data.content,
        authorName: isAuthenticated && user ? user.fullName : (data as GuestFormData).authorName,
        authorEmail: isAuthenticated && user ? user.email : (data as GuestFormData).authorEmail,
        parentCommentId,
      };

      const response = await commentsApi.create(payload);

      if (response.success && response.data) {
        onCommentAdded(response.data);
        toast.success(
          isAuthenticated
            ? 'Yorum gönderildi!'
            : 'Yorumunuz onay için gönderildi!'
        );

        if (isAuthenticated) {
          authForm.reset();
        } else {
          guestForm.reset();
        }

        onCancel?.();
      } else {
        toast.error(response.message || 'Yorum gönderilemedi');
      }
    } catch {
      toast.error('Yorum gönderilemedi');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isAuthenticated && user) {
    return (
      <div className={`font-mono border border-ide-border/50 rounded ${isReply ? 'border-l-2 border-l-ide-primary/50' : ''}`}>
        {/* Terminal header */}
        <div className="flex items-center justify-between px-3 py-2 bg-ide-sidebar border-b border-ide-border/50">
          <div className="flex items-center gap-2 text-xs">
            <Terminal className="w-3 h-3 text-ide-primary" />
            <span className="text-gray-500">
              {isReply ? 'reply.sh' : 'comment.sh'}
            </span>
          </div>
          {onCancel && (
            <button
              onClick={onCancel}
              className="text-gray-500 hover:text-red-400 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Form content */}
        <div className="p-4 space-y-3">
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <span className="text-gray-600">$</span>
            <span>commenting as</span>
            <span className="text-ide-primary">{user.fullName}</span>
          </div>

          <form onSubmit={authForm.handleSubmit(onSubmit)} className="space-y-3">
            <div>
              <textarea
                placeholder="// Yorumunuzu yazın..."
                className="w-full min-h-[80px] bg-transparent border border-ide-border/50 rounded px-3 py-2 text-sm text-gray-300 placeholder:text-gray-600 focus:outline-none focus:border-ide-primary/50 resize-none font-mono"
                {...authForm.register('content')}
              />
              {authForm.formState.errors.content && (
                <p className="text-xs text-red-400 mt-1">
                  <span className="text-red-500">✗</span> {authForm.formState.errors.content.message}
                </p>
              )}
            </div>

            <div className="flex gap-2">
              <button
                type="submit"
                disabled={isSubmitting}
                className="flex items-center gap-2 px-3 py-1.5 text-xs bg-ide-primary/10 border border-ide-primary/50 text-ide-primary rounded hover:bg-ide-primary/20 transition-colors disabled:opacity-50"
              >
                {isSubmitting ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Send className="w-3.5 h-3.5" />
                )}
                <span>{isReply ? 'yanıtla' : 'gönder'}</span>
              </button>
              {onCancel && (
                <button
                  type="button"
                  onClick={onCancel}
                  className="px-3 py-1.5 text-xs text-gray-500 border border-ide-border/50 rounded hover:text-gray-300 hover:border-ide-border transition-colors"
                >
                  iptal
                </button>
              )}
            </div>
          </form>
        </div>
      </div>
    );
  }

  // Guest form
  return (
    <div className={`font-mono border border-ide-border/50 rounded ${isReply ? 'border-l-2 border-l-ide-primary/50' : ''}`}>
      {/* Terminal header */}
      <div className="flex items-center justify-between px-3 py-2 bg-ide-sidebar border-b border-ide-border/50">
        <div className="flex items-center gap-2 text-xs">
          <Terminal className="w-3 h-3 text-ide-primary" />
          <span className="text-gray-500">
            {isReply ? (
              <span className="flex items-center gap-1">
                <CornerDownRight className="w-3 h-3" /> reply.sh
              </span>
            ) : 'comment.sh'}
          </span>
        </div>
        {onCancel && (
          <button
            onClick={onCancel}
            className="text-gray-500 hover:text-red-400 transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* Form content */}
      <div className="p-4 space-y-3">
        <form onSubmit={guestForm.handleSubmit(onSubmit)} className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="block text-[10px] text-gray-500 mb-1">
                <span className="text-gray-600">#</span> isim
              </label>
              <input
                className="w-full bg-transparent border border-ide-border/50 rounded px-3 py-1.5 text-sm text-gray-300 placeholder:text-gray-600 focus:outline-none focus:border-ide-primary/50 font-mono"
                placeholder="Adınız"
                {...guestForm.register('authorName')}
              />
              {guestForm.formState.errors.authorName && (
                <p className="text-xs text-red-400 mt-1">
                  <span className="text-red-500">✗</span> {guestForm.formState.errors.authorName.message}
                </p>
              )}
            </div>
            <div>
              <label className="block text-[10px] text-gray-500 mb-1">
                <span className="text-gray-600">#</span> email
              </label>
              <input
                type="email"
                className="w-full bg-transparent border border-ide-border/50 rounded px-3 py-1.5 text-sm text-gray-300 placeholder:text-gray-600 focus:outline-none focus:border-ide-primary/50 font-mono"
                placeholder="mail@example.com"
                {...guestForm.register('authorEmail')}
              />
              {guestForm.formState.errors.authorEmail && (
                <p className="text-xs text-red-400 mt-1">
                  <span className="text-red-500">✗</span> {guestForm.formState.errors.authorEmail.message}
                </p>
              )}
            </div>
          </div>

          <div>
            <label className="block text-[10px] text-gray-500 mb-1">
              <span className="text-gray-600">#</span> yorum
            </label>
            <textarea
              className="w-full min-h-[80px] bg-transparent border border-ide-border/50 rounded px-3 py-2 text-sm text-gray-300 placeholder:text-gray-600 focus:outline-none focus:border-ide-primary/50 resize-none font-mono"
              placeholder="// Yorumunuzu yazın..."
              {...guestForm.register('content')}
            />
            {guestForm.formState.errors.content && (
              <p className="text-xs text-red-400 mt-1">
                <span className="text-red-500">✗</span> {guestForm.formState.errors.content.message}
              </p>
            )}
          </div>

          <div className="text-[10px] text-gray-600">
            <span className="text-gray-600"># </span>
            Email yayınlanmayacak. Yorumlar moderasyondan geçebilir.
          </div>

          <div className="flex gap-2">
            <button
              type="submit"
              disabled={isSubmitting}
              className="flex items-center gap-2 px-3 py-1.5 text-xs bg-ide-primary/10 border border-ide-primary/50 text-ide-primary rounded hover:bg-ide-primary/20 transition-colors disabled:opacity-50"
            >
              {isSubmitting ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Send className="w-3.5 h-3.5" />
              )}
              <span>{isReply ? 'yanıtla' : 'gönder'}</span>
            </button>
            {onCancel && (
              <button
                type="button"
                onClick={onCancel}
                className="px-3 py-1.5 text-xs text-gray-500 border border-ide-border/50 rounded hover:text-gray-300 hover:border-ide-border transition-colors"
              >
                iptal
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
