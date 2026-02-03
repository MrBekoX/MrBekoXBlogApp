import { Skeleton } from '@/components/ui/skeleton';

export default function PostsLoading() {
  return (
    <div className="min-h-screen">
      <section className="border-b bg-gradient-to-br from-primary/5 via-background to-accent/5">
        <div className="container py-16 md:py-20">
          <div className="max-w-3xl mx-auto text-center space-y-6">
            <Skeleton className="h-8 w-32 mx-auto rounded-full" />
            <Skeleton className="h-12 w-80 mx-auto" />
            <Skeleton className="h-6 w-96 mx-auto" />
            <Skeleton className="h-12 w-full max-w-lg mx-auto" />
          </div>
        </div>
      </section>
      <section className="container py-12 md:py-16">
        <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 9 }).map((_, i) => (
            <div key={i} className="space-y-4">
              <Skeleton className="aspect-video w-full rounded-xl" />
              <Skeleton className="h-6 w-3/4" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
