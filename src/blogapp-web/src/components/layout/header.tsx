'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter, usePathname } from 'next/navigation';
import { useAuthStore } from '@/stores/auth-store';
import { useCategoriesStore } from '@/stores/categories-store';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { PenSquare, LogOut, LayoutDashboard, Menu, X, Home, BookOpen, FolderOpen, ChevronDown, Github, Linkedin } from 'lucide-react';
import { ThemeToggle } from '@/components/theme-toggle';
import { SearchCommand } from '@/components/search-command';

export function Header() {
  const router = useRouter();
  const pathname = usePathname();
  const user = useAuthStore((s) => s.user);
  const authStatus = useAuthStore((s) => s.authStatus);
  const logout = useAuthStore((s) => s.logout);
  const categories = useCategoriesStore((s) => s.categories);
  const fetchCategories = useCategoriesStore((s) => s.fetchCategories);
  const cacheVersion = useCategoriesStore((s) => s.cacheVersion);
  const isAuthenticated = authStatus === 'authenticated';
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Fetch categories on mount and when cache is invalidated
  useEffect(() => {
    fetchCategories().catch(() => { /* ignore */ });
  }, [fetchCategories, cacheVersion]);

  const handleLogout = async () => {
    await logout();
    router.push('/');
  };

  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map((n) => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  const handleHashNavigation = (e: React.MouseEvent<HTMLAnchorElement>, href: string) => {
    // Check if it's a hash link (like /#about)
    if (href.includes('#')) {
      const [path, hash] = href.split('#');
      const targetPath = path || '/';

      // If we're already on the target page, just scroll
      if (pathname === targetPath) {
        e.preventDefault();
        const element = document.getElementById(hash);
        if (element) {
          // Close mobile menu if open
          setMobileMenuOpen(false);
          
          // Smooth scroll with offset for fixed header
          const headerOffset = 80;
          const elementPosition = element.getBoundingClientRect().top;
          const offsetPosition = elementPosition + window.scrollY - headerOffset;

          window.scrollTo({
            top: offsetPosition,
            behavior: 'smooth'
          });
          
          // Update URL without triggering navigation
          window.history.pushState({}, '', href);
        }
      } else {
        // Navigating to different page with hash
        // Let Next.js Link handle this, then scroll on page load
        setMobileMenuOpen(false);
      }
    }
  };

  const isAuthorOrAbove = user?.role && ['Author', 'Editor', 'Admin'].includes(user.role);

  const navLinks = [
    { href: '/', label: 'Ana Sayfa', icon: Home },
    { href: '/posts', label: 'Yazılar', icon: BookOpen },
  ];

  const socialLinks = [
    { href: 'https://github.com/MrBekoX', icon: Github, label: 'GitHub' },
    { href: 'https://x.com/mrbeko_', icon: X, label: 'X' },
    { href: 'https://www.linkedin.com/in/berkay-kaplan-133b35245/', icon: Linkedin, label: 'LinkedIn' },
  ];

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/80 backdrop-blur-xl supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-16 items-center justify-between">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-3 group">
          <div className="relative w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-primary/60 flex items-center justify-center text-primary-foreground font-bold text-lg font-serif shadow-lg shadow-primary/20 group-hover:shadow-primary/40 transition-shadow">
            B
          </div>
          <div className="hidden sm:block">
            <span className="text-xl font-bold font-serif tracking-tight">
              MrBekoX
            </span>
            <span className="text-xs text-muted-foreground block -mt-1">Software Developer</span>
          </div>
        </Link>

        {/* Desktop Navigation */}
        <nav className="hidden md:flex items-center gap-1">
          {navLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={(e) => handleHashNavigation(e, link.href)}
              className="px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-primary hover:bg-primary/5 rounded-lg"
            >
              {link.label}
            </Link>
          ))}
          
          {/* Categories Dropdown */}
          {categories.length > 0 && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="px-4 py-2 h-auto text-sm font-medium text-muted-foreground hover:text-primary hover:bg-primary/5">
                  <FolderOpen className="mr-2 h-4 w-4" />
                  Kategoriler
                  <ChevronDown className="ml-1 h-3 w-3" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-48">
                {categories.map((category) => (
                  <DropdownMenuItem key={category.id} asChild>
                    <Link href={`/posts?categoryId=${category.id}`} className="cursor-pointer">
                      {category.name}
                      {category.postCount !== undefined && category.postCount > 0 && (
                        <span className="ml-auto text-xs text-muted-foreground">
                          {category.postCount}
                        </span>
                      )}
                    </Link>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </nav>

        {/* Right Side Actions */}
        <div className="flex items-center gap-2">
          <div className="hidden sm:block">
            <SearchCommand />
          </div>
          
          {/* Social Links */}
          <div className="hidden md:flex items-center gap-1">
            {socialLinks.map((social) => {
              const Icon = social.icon;
              return (
                <Button
                  key={social.label}
                  variant="ghost"
                  size="icon"
                  asChild
                  className="h-9 w-9 hover:text-primary"
                >
                  <a href={social.href} target="_blank" rel="noopener noreferrer" aria-label={social.label}>
                    <Icon className="h-4 w-4" />
                  </a>
                </Button>
              );
            })}
          </div>
          
          <ThemeToggle />
          
          {isAuthenticated && user && (
            <>
              {isAuthorOrAbove && (
                <Button asChild variant="default" size="sm" className="hidden sm:flex">
                  <Link href="/mrbekox-console/dashboard/posts/new">
                    <PenSquare className="mr-2 h-4 w-4" />
                    Yeni Yazı
                  </Link>
                </Button>
              )}

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" className="relative h-10 w-10 rounded-full ring-2 ring-primary/20 hover:ring-primary/40 transition-all">
                    <Avatar className="h-10 w-10">
                      <AvatarImage src={user.avatarUrl} alt={user.fullName} />
                      <AvatarFallback className="bg-primary/10 text-primary font-semibold">
                        {getInitials(user.fullName || user.userName)}
                      </AvatarFallback>
                    </Avatar>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent className="w-56" align="end" forceMount>
                  <div className="flex items-center justify-start gap-2 p-2">
                    <div className="flex flex-col space-y-1 leading-none">
                      <p className="font-medium">{user.fullName || user.userName}</p>
                      <p className="w-[200px] truncate text-sm text-muted-foreground">
                        {user.email}
                      </p>
                    </div>
                  </div>
                  <DropdownMenuSeparator />
                  {isAuthorOrAbove && (
                    <DropdownMenuItem asChild>
                      <Link href="/mrbekox-console/dashboard" className="cursor-pointer">
                        <LayoutDashboard className="mr-2 h-4 w-4" />
                        Kontrol Paneli
                      </Link>
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={handleLogout} className="cursor-pointer text-destructive focus:text-destructive">
                    <LogOut className="mr-2 h-4 w-4" />
                    Çıkış Yap
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </>
          )}

          {/* Mobile Menu Button */}
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label={mobileMenuOpen ? 'Menüyü kapat' : 'Menüyü aç'}
            aria-expanded={mobileMenuOpen}
          >
            {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </Button>
        </div>
      </div>

      {/* Mobile Menu */}
      {mobileMenuOpen && (
        <div className="md:hidden border-t bg-background/95 backdrop-blur-xl">
          <div className="container py-4 space-y-4">
            <nav className="flex flex-col gap-2">
              {navLinks.map((link) => {
                const Icon = link.icon;
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    onClick={(e) => {
                      handleHashNavigation(e, link.href);
                      setMobileMenuOpen(false);
                    }}
                    className="flex items-center gap-3 px-4 py-3 text-sm font-medium text-muted-foreground transition-colors hover:text-primary hover:bg-primary/5 rounded-lg"
                  >
                    <Icon className="h-4 w-4" />
                    {link.label}
                  </Link>
                );
              })}
            </nav>
            
            {/* Mobile Categories */}
            {categories.length > 0 && (
              <div className="px-4 pt-2 border-t">
                <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-2">
                  <FolderOpen className="h-3 w-3" />
                  Kategoriler
                </p>
                <div className="flex flex-wrap gap-2">
                  {categories.map((category) => (
                    <Link
                      key={category.id}
                      href={`/posts?categoryId=${category.id}`}
                      onClick={() => setMobileMenuOpen(false)}
                      className="px-3 py-1.5 text-xs font-medium bg-primary/5 hover:bg-primary/10 text-primary rounded-full transition-colors"
                    >
                      {category.name}
                    </Link>
                  ))}
                </div>
              </div>
            )}
            
            {/* Mobile Social Links */}
            <div className="flex items-center gap-2 px-4 pt-2 border-t">
              {socialLinks.map((social) => {
                const Icon = social.icon;
                return (
                  <Button
                    key={social.label}
                    variant="ghost"
                    size="icon"
                    asChild
                    className="h-9 w-9 hover:text-primary"
                  >
                    <a href={social.href} target="_blank" rel="noopener noreferrer" aria-label={social.label}>
                      <Icon className="h-4 w-4" />
                    </a>
                  </Button>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
