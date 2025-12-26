import Link from 'next/link';
import { Github, X, Linkedin, Mail, Heart, Coffee, ArrowUpRight } from 'lucide-react';
import { Button } from '@/components/ui/button';

export function Footer() {
  const currentYear = new Date().getFullYear();

  const socialLinks = [
    { href: 'https://github.com/MrBekoX', icon: Github, label: 'GitHub' },
    { href: 'https://x.com/mrbeko_', icon: X, label: 'X' },
    { href: 'https://www.linkedin.com/in/berkay-kaplan-133b35245/', icon: Linkedin, label: 'LinkedIn' },
    { href: 'mailto:hello@mrbekox.com', icon: Mail, label: 'Email' },
  ];

  const navigationLinks = [
    { href: '/', label: 'Ana Sayfa' },
    { href: '/posts', label: 'Yazılar' },
    { href: '/#about', label: 'Hakkımda' },
  ];

  const resourceLinks = [
    { href: '/categories', label: 'Kategoriler' },
    { href: '/tags', label: 'Etiketler' },
  ];

  return (
    <footer className="border-t bg-muted/30">
      <div className="container py-12 md:py-16">
        <div className="grid gap-12 md:grid-cols-2 lg:grid-cols-4">
          {/* Brand Section */}
          <div className="lg:col-span-2 space-y-6">
            <Link href="/" className="flex items-center gap-3 group">
              <div className="relative w-12 h-12 rounded-xl bg-gradient-to-br from-primary to-primary/60 flex items-center justify-center text-primary-foreground font-bold text-xl font-serif shadow-lg shadow-primary/20">
                B
              </div>
              <div>
                <span className="text-2xl font-bold font-serif tracking-tight">
                  MrBekoX
                </span>
                <span className="text-sm text-muted-foreground block">Kişisel Blog</span>
              </div>
            </Link>
            
            <p className="text-muted-foreground max-w-md leading-relaxed">
              Yazılım, teknoloji ve yaşam üzerine düşünceler. Kod yazarken öğrendiklerimi, 
              deneyimlerimi ve projelerimi paylaştığım kişisel alan.
            </p>

            {/* Social Links */}
            <div className="flex gap-2">
              {socialLinks.map((social) => {
                const Icon = social.icon;
                return (
                  <Button
                    key={social.label}
                    variant="outline"
                    size="icon"
                    asChild
                    className="hover:text-primary hover:border-primary hover:bg-primary/5 transition-all"
                  >
                    <Link href={social.href} target="_blank" aria-label={social.label}>
                      <Icon className="h-4 w-4" />
                    </Link>
                  </Button>
                );
              })}
            </div>
          </div>

          {/* Navigation */}
          <div className="space-y-4">
            <h3 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground">
              Navigasyon
            </h3>
            <ul className="space-y-3">
              {navigationLinks.map((link) => (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    className="text-foreground/80 hover:text-primary transition-colors inline-flex items-center gap-1 group"
                  >
                    {link.label}
                    <ArrowUpRight className="h-3 w-3 opacity-0 -translate-y-1 translate-x-1 group-hover:opacity-100 group-hover:translate-y-0 group-hover:translate-x-0 transition-all" />
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Resources */}
          <div className="space-y-4">
            <h3 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground">
              Keşfet
            </h3>
            <ul className="space-y-3">
              {resourceLinks.map((link) => (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    className="text-foreground/80 hover:text-primary transition-colors inline-flex items-center gap-1 group"
                  >
                    {link.label}
                    <ArrowUpRight className="h-3 w-3 opacity-0 -translate-y-1 translate-x-1 group-hover:opacity-100 group-hover:translate-y-0 group-hover:translate-x-0 transition-all" />
                  </Link>
                </li>
              ))}
              <li>
                <Link
                  href="/login"
                  className="text-foreground/80 hover:text-primary transition-colors inline-flex items-center gap-1 group"
                >
                  Giriş Yap
                  <ArrowUpRight className="h-3 w-3 opacity-0 -translate-y-1 translate-x-1 group-hover:opacity-100 group-hover:translate-y-0 group-hover:translate-x-0 transition-all" />
                </Link>
              </li>
            </ul>
          </div>
        </div>

        {/* Bottom Section */}
        <div className="mt-12 pt-8 border-t">
          <div className="flex flex-col md:flex-row justify-between items-center gap-4">
            <p className="text-sm text-muted-foreground flex items-center gap-1">
              © {currentYear} MrBekoX. Tüm hakları saklıdır.
            </p>
            
            <p className="text-sm text-muted-foreground flex items-center gap-1">
              <span>Sevgiyle</span>
              <Heart className="h-4 w-4 text-destructive fill-current" />
              <span>ve</span>
              <Coffee className="h-4 w-4 text-primary" />
              <span>ile yapıldı</span>
            </p>
          </div>
        </div>
      </div>
    </footer>
  );
}
