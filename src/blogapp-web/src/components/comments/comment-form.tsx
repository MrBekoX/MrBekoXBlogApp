'use client';

import * as React from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod/v4';
import { commentsApi } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { toast } from 'sonner';
import { Loader2, Send } from 'lucide-react';
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
            ? 'Comment posted!'
            : 'Comment submitted! It will appear after approval.'
        );
        
        if (isAuthenticated) {
          authForm.reset();
        } else {
          guestForm.reset();
        }
        
        onCancel?.();
      } else {
        toast.error(response.message || 'Failed to post comment');
      }
    } catch (error) {
      toast.error('Failed to post comment');
      console.error('Comment error:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isAuthenticated && user) {
    return (
      <Card className={isReply ? 'border-l-4 border-l-primary/30' : ''}>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">
            {isReply ? 'Reply' : 'Leave a comment'}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={authForm.handleSubmit(onSubmit)} className="space-y-4">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>Commenting as</span>
              <span className="font-medium text-foreground">{user.fullName}</span>
            </div>
            
            <div className="space-y-2">
              <Textarea
                placeholder="Write your comment..."
                className="min-h-[100px]"
                {...authForm.register('content')}
              />
              {authForm.formState.errors.content && (
                <p className="text-sm text-destructive">
                  {authForm.formState.errors.content.message}
                </p>
              )}
            </div>

            <div className="flex gap-2">
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Send className="mr-2 h-4 w-4" />
                )}
                {isReply ? 'Reply' : 'Post Comment'}
              </Button>
              {onCancel && (
                <Button type="button" variant="outline" onClick={onCancel}>
                  Cancel
                </Button>
              )}
            </div>
          </form>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={isReply ? 'border-l-4 border-l-primary/30' : ''}>
      <CardHeader className="pb-3">
        <CardTitle className="text-lg">
          {isReply ? 'Reply' : 'Leave a comment'}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={guestForm.handleSubmit(onSubmit)} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="authorName">Name</Label>
              <Input
                id="authorName"
                placeholder="Your name"
                {...guestForm.register('authorName')}
              />
              {guestForm.formState.errors.authorName && (
                <p className="text-sm text-destructive">
                  {guestForm.formState.errors.authorName.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="authorEmail">Email</Label>
              <Input
                id="authorEmail"
                type="email"
                placeholder="your@email.com"
                {...guestForm.register('authorEmail')}
              />
              {guestForm.formState.errors.authorEmail && (
                <p className="text-sm text-destructive">
                  {guestForm.formState.errors.authorEmail.message}
                </p>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="content">Comment</Label>
            <Textarea
              id="content"
              placeholder="Write your comment..."
              className="min-h-[100px]"
              {...guestForm.register('content')}
            />
            {guestForm.formState.errors.content && (
              <p className="text-sm text-destructive">
                {guestForm.formState.errors.content.message}
              </p>
            )}
          </div>

          <p className="text-xs text-muted-foreground">
            Your email will not be published. Comments are moderated and may take time to appear.
          </p>

          <div className="flex gap-2">
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Send className="mr-2 h-4 w-4" />
              )}
              {isReply ? 'Reply' : 'Submit Comment'}
            </Button>
            {onCancel && (
              <Button type="button" variant="outline" onClick={onCancel}>
                Cancel
              </Button>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

