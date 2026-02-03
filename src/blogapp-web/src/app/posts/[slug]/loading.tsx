import { Skeleton } from '@/components/ui/skeleton';

export default function PostLoading() {
  return (
    <div className="container max-w-4xl py-12">
      <Skeleton className="h-8 w-32" />
      <Skeleton className="mt-8 h-12 w-3/4" />
      <div className="mt-4 flex gap-2">
        <Skeleton className="h-6 w-20" />
        <Skeleton className="h-6 w-20" />
      </div>
      <Skeleton className="mt-8 aspect-video w-full rounded-lg" />
      <div className="mt-8 space-y-4">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
      </div>
    </div>
  );
}
