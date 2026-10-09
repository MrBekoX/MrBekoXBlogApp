import { Skeleton } from '@/components/ui/skeleton';

export default function HomeLoading() {
  return (
    <div className="max-w-3xl font-mono">
      <Skeleton className="h-12 w-3/4 mb-4 bg-ide-border" />
      <div className="flex gap-4 mb-8">
        <Skeleton className="h-3 w-20 bg-ide-border" />
        <Skeleton className="h-3 w-24 bg-ide-border" />
      </div>
      <Skeleton className="h-32 w-full rounded mb-8 bg-ide-border" />
      <Skeleton className="h-4 w-40 mb-4 bg-ide-border" />
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-14 w-full rounded bg-ide-border" />
        ))}
      </div>
    </div>
  );
}
