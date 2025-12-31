import { Metadata } from 'next';

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'https://mrbekox.dev';

export const metadata: Metadata = {
  title: 'Yazılar & Düşünceler',
  description: 'Backend geliştirme, yazılım mimarisi, AI teknolojileri, mikroservisler ve modern sistem tasarımı hakkında teknik makaleler ve düşünceler. .NET, C#, Python, Clean Architecture ve CQRS konularında derinlemesine içerikler.',
  keywords: [
    'backend makaleleri',
    'yazılım mimarisi blog',
    'AI teknolojileri',
    'mikroservis örnekleri',
    'sistem tasarımı',
    '.NET Core tutorial',
    'C# best practices',
    'clean architecture',
    'CQRS pattern',
    'domain driven design',
    'teknik blog türkçe',
  ],
  openGraph: {
    title: 'Yazılar & Düşünceler | MrBekoX Blog',
    description: 'Backend geliştirme, yazılım mimarisi ve AI teknolojileri hakkında teknik makaleler.',
    url: `${SITE_URL}/posts`,
    type: 'website',
    images: [
      {
        url: '/opengraph-image',
        width: 1200,
        height: 630,
        alt: 'MrBekoX Blog Yazıları',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Yazılar & Düşünceler | MrBekoX Blog',
    description: 'Backend geliştirme, yazılım mimarisi ve AI teknolojileri hakkında teknik makaleler.',
    images: ['/opengraph-image'],
  },
  alternates: {
    canonical: `${SITE_URL}/posts`,
  },
};

export default function PostsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}

