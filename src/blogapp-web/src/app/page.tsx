import Link from "next/link";
import { fetchPosts, fetchTags } from "@/lib/server-api";
import { HomePostsSection, HomeTagsSection } from "@/components/home";
import { Button } from "@/components/ui/button";
import {
  ArrowRight,
  Code2,
  Coffee,
  Sparkles,
  Github,
  X,
  Linkedin,
  BookOpen,
  Terminal,
} from "lucide-react";

export default async function HomePage() {
  // Fetch data on the server
  const [postsData, tagsData] = await Promise.all([
    fetchPosts({ pageSize: 6, status: "Published", sortBy: "publishedat", sortDescending: true }),
    fetchTags()
  ]);

  const posts = postsData?.items || [];
  const tags = tagsData || [];

  return (
    <div className="relative">
      {/* Background decoration */}
      <div className="fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute top-0 left-1/4 w-96 h-96 bg-primary/5 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-accent/10 rounded-full blur-3xl" />
      </div>

      {/* Hero Section */}
      <section className="relative min-h-[85vh] flex items-center">
        <div className="container py-16 md:py-24">
          <div className="flex flex-col items-center text-center">
            {/* Avatar/Visual */}
            <div className="relative mb-8 animate-fade-in">
              <div className="relative">
                {/* Decorative rings */}
                <div
                  className="absolute inset-0 rounded-full border-2 border-dashed border-primary/20 animate-[spin_20s_linear_infinite]"
                  style={{
                    width: "120%",
                    height: "120%",
                    left: "-10%",
                    top: "-10%",
                  }}
                />
                <div
                  className="absolute inset-0 rounded-full border-2 border-dashed border-accent/20 animate-[spin_30s_linear_infinite_reverse]"
                  style={{
                    width: "140%",
                    height: "140%",
                    left: "-20%",
                    top: "-20%",
                  }}
                />

                {/* Main avatar container */}
                <div className="relative w-48 h-48 md:w-56 md:h-56 rounded-full overflow-hidden border-2 border-primary/20 shadow-2xl shadow-primary/10">
                  <img
                    src="/images/avatar.jpg"
                    alt="MrBekoX"
                    className="w-full h-full object-cover"
                  />
                </div>

                {/* Floating badges */}
                <div className="absolute -top-2 -right-2 px-3 py-1.5 rounded-xl bg-card border border-border shadow-lg animate-float">
                  <Code2 className="w-5 h-5 text-primary" />
                </div>
                <div
                  className="absolute -bottom-2 -left-2 px-3 py-1.5 rounded-xl bg-card border border-border shadow-lg animate-float"
                  style={{ animationDelay: "1s" }}
                >
                  <Terminal className="w-5 h-5 text-primary" />
                </div>
                <div
                  className="absolute top-1/2 -right-6 px-3 py-1.5 rounded-xl bg-card border border-border shadow-lg animate-float"
                  style={{ animationDelay: "2s" }}
                >
                  <Sparkles className="w-5 h-5 text-primary" />
                </div>
              </div>
            </div>

            {/* Text Content */}
            <div className="space-y-8 animate-fade-in-up max-w-3xl">
              <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 border border-primary/20 text-sm text-primary">
                <Coffee className="w-4 h-4" />
                <span>Kod &amp; Kahve &amp; Yaratıcılık</span>
              </div>

              <div className="space-y-4">
                <h1 className="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-bold tracking-tight leading-tight">
                  Merhaba, ben{" "}
                  <span className="relative inline-block">
                    <span className="bg-gradient-to-r from-primary via-primary/80 to-accent bg-clip-text text-transparent">
                      MrBekoX
                    </span>
                    <span className="absolute -bottom-2 left-0 w-full h-1 bg-gradient-to-r from-primary to-accent rounded-full" />
                  </span>
                </h1>
              </div>

              <div className="flex flex-wrap gap-4 justify-center">
                <Button asChild size="lg" className="group">
                  <Link href="/posts">
                    <BookOpen className="mr-2 h-5 w-5" />
                    Yazıları Keşfet
                    <ArrowRight className="ml-2 h-4 w-4 transition-transform group-hover:translate-x-1" />
                  </Link>
                </Button>
              </div>

              {/* Social Links */}
              <div className="flex items-center justify-center gap-4 pt-4">
                <span className="text-sm text-muted-foreground">
                  Beni takip edin:
                </span>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="icon"
                    asChild
                    className="hover:text-primary hover:bg-primary/10"
                  >
                    <a
                      href="https://github.com/MrBekoX"
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label="GitHub"
                    >
                      <Github className="h-5 w-5" />
                    </a>
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    asChild
                    className="hover:text-primary hover:bg-primary/10"
                  >
                    <a
                      href="https://x.com/mrbeko_"
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label="X"
                    >
                      <X className="h-5 w-5" />
                    </a>
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    asChild
                    className="hover:text-primary hover:bg-primary/10"
                  >
                    <a
                      href="https://www.linkedin.com/in/berkay-kaplan-133b35245/"
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label="LinkedIn"
                    >
                      <Linkedin className="h-5 w-5" />
                    </a>
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Popular Tags Section - Client Component for cache sync */}
      <HomeTagsSection initialTags={tags} />

      {/* Latest Posts Section - Client Component for cache sync */}
      <HomePostsSection initialPosts={posts} />
    </div>
  );
}
