import { Skeleton } from '@/components/ui/skeleton';

export default function PostLoading() {
  return (
    <div className="max-w-3xl font-mono">
      <Skeleton className="h-4 w-24 mb-8 bg-ide-border" />
      <Skeleton className="h-10 w-3/4 mb-4 bg-ide-border" />
      <div className="flex gap-3 mb-8">
        <Skeleton className="h-3 w-20 bg-ide-border" />
        <Skeleton className="h-3 w-24 bg-ide-border" />
        <Skeleton className="h-3 w-16 bg-ide-border" />
      </div>
      <Skeleton className="aspect-video w-full rounded mb-8 bg-ide-border" />
      <div className="space-y-3">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-3 w-full bg-ide-border" style={{ width: `${70 + Math.random() * 30}%` }} />
        ))}
      </div>
    </div>
  );
}
