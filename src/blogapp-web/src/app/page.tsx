"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePostsStore } from "@/stores/posts-store";
import { PostCard } from "@/components/posts/post-card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
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
  Lightbulb,
} from "lucide-react";

export default function HomePage() {
  const { posts, isLoading, fetchPosts, cacheVersion } = usePostsStore();

  // Refetch when cache is invalidated (cacheVersion changes)
  useEffect(() => {
    fetchPosts({ pageSize: 6, status: "Published" }, true);
  }, [cacheVersion, fetchPosts]);

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
                <span>Kod & Kahve & Yaratıcılık</span>
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
                <p className="text-xl md:text-2xl text-muted-foreground leading-relaxed mx-auto max-w-2xl">
                  Yazılım geliştirici, teknoloji meraklısı ve sürekli öğrenen
                  biri. Bu blogda kod yazarken öğrendiklerimi, projelerimi ve
                  düşüncelerimi paylaşıyorum.
                </p>
              </div>

              <div className="flex flex-wrap gap-4 justify-center">
                <Button asChild size="lg" className="group">
                  <Link href="/posts">
                    <BookOpen className="mr-2 h-5 w-5" />
                    Yazıları Keşfet
                    <ArrowRight className="ml-2 h-4 w-4 transition-transform group-hover:translate-x-1" />
                  </Link>
                </Button>
                <Button asChild variant="outline" size="lg">
                  <a href="#about">Hakkımda</a>
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

      {/* About Section */}
      <section id="about" className="border-t bg-muted/30">
        <div className="container py-20 md:py-28">
          <div className="mx-auto max-w-4xl">
            <div className="text-left space-y-4 mb-16 animate-fade-in-up">
              <h2 className="text-3xl md:text-4xl font-bold tracking-tight">
                Hakkımda
              </h2>
              <div className="w-20 h-1 bg-gradient-to-r from-primary to-accent rounded-full" />
            </div>

            <div className="grid md:grid-cols-3 gap-8">
              <div className="group p-8 rounded-2xl bg-card border border-border hover:border-primary/50 transition-all hover:shadow-lg hover:shadow-primary/5">
                <div className="w-14 h-14 rounded-xl bg-primary/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
                  <Code2 className="w-7 h-7 text-primary" />
                </div>
                <h3 className="text-xl font-semibold mb-3">
                  Yazılım Geliştirme
                </h3>
                <p className="text-muted-foreground leading-relaxed">
                  Full-stack yazılım geliştirme yapıyorum; ağırlıklı olarak
                  backend mimarileri ve iş mantığına odaklanıyor, temiz kod
                  yazmaya tutkuyla bağlıyım.
                </p>
              </div>

              <div className="group p-8 rounded-2xl bg-card border border-border hover:border-primary/50 transition-all hover:shadow-lg hover:shadow-primary/5">
                <div className="w-14 h-14 rounded-xl bg-primary/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
                  <Lightbulb className="w-7 h-7 text-primary" />
                </div>
                <h3 className="text-xl font-semibold mb-3">
                  Öğrenme & Paylaşma
                </h3>
                <p className="text-muted-foreground leading-relaxed">
                  Her gün yeni bir şey öğrenmeyi ve bu bilgiyi toplulukla
                  paylaşmayı seviyorum. Bu blog, o yolculuğun bir parçası.
                </p>
              </div>

              <div className="group p-8 rounded-2xl bg-card border border-border hover:border-primary/50 transition-all hover:shadow-lg hover:shadow-primary/5">
                <div className="w-14 h-14 rounded-xl bg-primary/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
                  <Coffee className="w-7 h-7 text-primary" />
                </div>
                <h3 className="text-xl font-semibold mb-3">Yaşam & İlham</h3>
                <p className="text-muted-foreground leading-relaxed">
                  Kod dışında müzik, kitaplar ve kahve ile ilgileniyorum. Bazen
                  de teknoloji dışı konularda yazılar paylaşıyorum.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Latest Posts Section */}
      <section className="border-t">
        <div className="container py-20 md:py-28">
          {/* Section Header - Centered */}
          <div className="text-center space-y-4 mb-12">
            <h2 className="text-3xl md:text-4xl font-bold tracking-tight">
              Son Yazılar
            </h2>
            <p className="text-muted-foreground text-lg max-w-2xl mx-auto">
              En son paylaştığım yazılar ve düşünceler
            </p>
          </div>

          {/* Posts Grid */}
          <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-3 max-w-6xl mx-auto">
            {isLoading ? (
              Array.from({ length: 6 }).map((_, i) => (
                <div
                  key={i}
                  className="space-y-4 animate-fade-in"
                  style={{ animationDelay: `${i * 0.1}s` }}
                >
                  <Skeleton className="aspect-video w-full rounded-xl" />
                  <Skeleton className="h-6 w-3/4" />
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-2/3" />
                </div>
              ))
            ) : posts?.items?.length ? (
              posts.items.map((post, index) => (
                <div
                  key={post.id}
                  className="animate-fade-in-up"
                  style={{ animationDelay: `${index * 0.1}s` }}
                >
                  <PostCard post={post} />
                </div>
              ))
            ) : (
              <div className="col-span-full text-center py-16">
                <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-muted flex items-center justify-center">
                  <BookOpen className="w-10 h-10 text-muted-foreground" />
                </div>
                <p className="text-xl text-muted-foreground mb-4">
                  Henüz yazı yok
                </p>
                <p className="text-muted-foreground mb-6">
                  Yakında yeni içerikler eklenecek!
                </p>
              </div>
            )}
          </div>

          {/* View All Button - Centered */}
          {posts?.items?.length ? (
            <div className="text-center mt-12">
              <Button asChild variant="outline" size="lg" className="group">
                <Link href="/posts">
                  Tüm Yazılar
                  <ArrowRight className="ml-2 h-4 w-4 transition-transform group-hover:translate-x-1" />
                </Link>
              </Button>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
