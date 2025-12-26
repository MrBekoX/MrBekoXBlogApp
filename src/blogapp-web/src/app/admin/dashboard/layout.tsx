'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuthStore } from '@/stores/auth-store';
import { cn } from '@/lib/utils';
import { LayoutDashboard, FileText, FolderOpen, Tags, Settings, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';

const sidebarItems = [
  { href: '/admin/dashboard', label: 'Genel Bakış', icon: LayoutDashboard },
  { href: '/admin/dashboard/posts', label: 'Yazılar', icon: FileText },
  { href: '/admin/dashboard/categories', label: 'Kategoriler', icon: FolderOpen },
  { href: '/admin/dashboard/tags', label: 'Etiketler', icon: Tags },
  { href: '/admin/dashboard/settings', label: 'Ayarlar', icon: Settings },
];

export default function AdminDashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, isAuthenticated, checkAuth } = useAuthStore();

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  useEffect(() => {
    if (!isAuthenticated) {
      router.push('/admin');
    }
  }, [isAuthenticated, router]);

  const isAuthorOrAbove = user?.role && ['Author', 'Editor', 'Admin'].includes(user.role);

  if (!isAuthenticated || !isAuthorOrAbove) {
    return (
      <div className="container flex min-h-[50vh] items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold">Erişim Engellendi</h1>
          <p className="mt-2 text-muted-foreground">
            Bu sayfaya erişim yetkiniz bulunmuyor.
          </p>
          <Button asChild className="mt-4">
            <Link href="/">Ana Sayfaya Dön</Link>
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="container flex min-h-[calc(100vh-16rem)] gap-8 py-8">
      <aside className="hidden w-64 shrink-0 md:block">
        <nav className="sticky top-24 space-y-2">
          <Button asChild className="mb-4 w-full">
            <Link href="/admin/dashboard/posts/new">
              <Plus className="mr-2 h-4 w-4" />
              Yeni Yazı
            </Link>
          </Button>

          {sidebarItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors',
                pathname === item.href
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              )}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>

      <main className="flex-1">{children}</main>
    </div>
  );
}

