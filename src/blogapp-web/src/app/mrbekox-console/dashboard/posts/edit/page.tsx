'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { EditPostForm } from '@/components/admin/edit-post-form';
import { Loader2 } from 'lucide-react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { ArrowLeft } from 'lucide-react';

function EditPostContent() {
  const searchParams = useSearchParams();
  const postId = searchParams.get('id');

  if (!postId) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] gap-4">
        <p className="text-muted-foreground">Yazı ID&apos;si belirtilmedi</p>
        <Link href="/mrbekox-console/dashboard/posts">
          <Button variant="outline">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Yazılara Dön
          </Button>
        </Link>
      </div>
    );
  }

  return <EditPostForm postId={postId} />;
}

function EditPostLoading() {
  return (
    <div className="flex items-center justify-center min-h-[400px]">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
    </div>
  );
}

export default function EditPostPage() {
  return (
    <Suspense fallback={<EditPostLoading />}>
      <EditPostContent />
    </Suspense>
  );
}
