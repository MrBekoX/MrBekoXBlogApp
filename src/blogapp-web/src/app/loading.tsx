import { Skeleton } from "@/components/ui/skeleton";

export default function HomeLoading() {
  return (
    <div className="relative">
      {/* Background decoration */}
      <div className="fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute top-0 left-1/4 w-96 h-96 bg-primary/5 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-accent/10 rounded-full blur-3xl" />
      </div>

      {/* Hero Section Skeleton */}
      <section className="relative min-h-[85vh] flex items-center">
        <div className="container py-16 md:py-24">
          <div className="flex flex-col items-center text-center">
            {/* Avatar Skeleton */}
            <Skeleton className="w-48 h-48 md:w-56 md:h-56 rounded-full mb-8" />

            {/* Text Content Skeleton */}
            <div className="space-y-8 max-w-3xl w-full">
              <Skeleton className="h-8 w-48 mx-auto rounded-full" />
              <Skeleton className="h-16 w-3/4 mx-auto" />
              <div className="flex flex-wrap gap-4 justify-center">
                <Skeleton className="h-12 w-40" />
              </div>
              <div className="flex items-center justify-center gap-4 pt-4">
                <Skeleton className="h-10 w-10 rounded-full" />
                <Skeleton className="h-10 w-10 rounded-full" />
                <Skeleton className="h-10 w-10 rounded-full" />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Tags Section Skeleton */}
      <section className="border-t bg-muted/30">
        <div className="container py-12 md:py-16">
          <div className="text-center space-y-4 mb-8">
            <Skeleton className="h-8 w-40 mx-auto rounded-full" />
            <Skeleton className="h-10 w-64 mx-auto" />
          </div>
          <div className="flex flex-wrap justify-center gap-3 max-w-4xl mx-auto">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-24 rounded-full" />
            ))}
          </div>
        </div>
      </section>

      {/* Posts Section Skeleton */}
      <section className="border-t">
        <div className="container py-20 md:py-28">
          <div className="text-center space-y-4 mb-12">
            <Skeleton className="h-12 w-48 mx-auto" />
            <Skeleton className="h-6 w-96 mx-auto" />
          </div>
          <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-3 max-w-6xl mx-auto">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="space-y-4">
                <Skeleton className="aspect-video w-full rounded-xl" />
                <Skeleton className="h-6 w-3/4" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-2/3" />
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
