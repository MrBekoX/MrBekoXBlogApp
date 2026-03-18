import { Skeleton } from '@/components/ui/skeleton';

export default function PostsLoading() {
  return (
    <div className="font-mono">
      <Skeleton className="h-8 w-48 mb-6 bg-ide-border" />
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 9 }).map((_, i) => (
          <div key={i} className="space-y-3 p-4 border border-ide-border rounded">
            <Skeleton className="aspect-video w-full rounded bg-ide-border" />
            <Skeleton className="h-4 w-3/4 bg-ide-border" />
            <Skeleton className="h-3 w-full bg-ide-border" />
            <Skeleton className="h-3 w-2/3 bg-ide-border" />
          </div>
        ))}
      </div>
    </div>
  );
}
