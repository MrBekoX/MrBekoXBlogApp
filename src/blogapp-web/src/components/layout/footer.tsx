import Link from 'next/link';
import { Github, X, Linkedin, Mail, Heart, Coffee } from 'lucide-react';
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
        {/* Centered Content */}
        <div className="flex flex-col items-center text-center space-y-8">
          {/* Brand */}
          <Link href="/" className="flex items-center gap-3 group">
            <div className="relative w-12 h-12 rounded-xl bg-gradient-to-br from-primary to-primary/60 flex items-center justify-center text-primary-foreground font-bold text-xl font-serif shadow-lg shadow-primary/20">
              B
            </div>
            <div className="text-left">
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

          {/* Navigation Links */}
          <div className="flex flex-wrap justify-center gap-6">
            {navigationLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="text-foreground/80 hover:text-primary transition-colors"
              >
                {link.label}
              </Link>
            ))}
            {resourceLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="text-foreground/80 hover:text-primary transition-colors"
              >
                {link.label}
              </Link>
            ))}
          </div>

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
                  <a href={social.href} target="_blank" rel="noopener noreferrer" aria-label={social.label}>
                    <Icon className="h-4 w-4" />
                  </a>
                </Button>
              );
            })}
          </div>
        </div>

        {/* Bottom Section */}
        <div className="mt-12 pt-8 border-t">
          <div className="flex flex-col md:flex-row justify-center items-center gap-4 text-center">
            <p className="text-sm text-muted-foreground flex items-center gap-1">
              © {currentYear} MrBekoX. Tüm hakları saklıdır.
            </p>

            <span className="hidden md:inline text-muted-foreground">•</span>

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
