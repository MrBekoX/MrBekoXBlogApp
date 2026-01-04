'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuthStore } from '@/stores/auth-store';
import { AuthGuard } from '@/components/auth/auth-guard';
import { cn } from '@/lib/utils';
import { LayoutDashboard, FileText, FolderOpen, Tags, Settings, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';

const sidebarItems = [
  { href: '/mrbekox-console/dashboard', label: 'Genel Bakış', icon: LayoutDashboard },
  { href: '/mrbekox-console/dashboard/posts', label: 'Yazılar', icon: FileText },
  { href: '/mrbekox-console/dashboard/categories', label: 'Kategoriler', icon: FolderOpen },
  { href: '/mrbekox-console/dashboard/tags', label: 'Etiketler', icon: Tags },
  { href: '/mrbekox-console/dashboard/settings', label: 'Ayarlar', icon: Settings },
];

function DashboardContent({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="container flex min-h-[calc(100vh-16rem)] gap-8 py-8">
      <aside className="hidden w-64 shrink-0 md:block">
        <nav className="sticky top-24 space-y-2">
          <Button asChild className="mb-4 w-full">
            <Link href="/mrbekox-console/dashboard/posts/new">
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

export default function AdminDashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard allowedRoles={['Author', 'Editor', 'Admin']}>
      <DashboardContent>{children}</DashboardContent>
    </AuthGuard>
  );
}

