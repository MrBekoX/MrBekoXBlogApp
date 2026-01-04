import type { Metadata } from 'next';
import { Playfair_Display, Source_Sans_3, JetBrains_Mono, Merriweather, Crimson_Text } from 'next/font/google';
import { Header } from '@/components/layout/header';
import { Footer } from '@/components/layout/footer';
import { Toaster } from '@/components/ui/sonner';
import { ThemeProvider } from '@/components/theme-provider';
import { CacheSyncProvider } from '@/components/cache-sync-provider';
import { ErrorBoundary } from '@/components/error-boundary';
import { OrganizationSchema } from '@/components/seo/organization-schema';
import { WebsiteSchema } from '@/components/seo/website-schema';
import { PersonSchema } from '@/components/seo/person-schema';
import './globals.css';

// Google Fonts with Next.js optimization
const playfairDisplay = Playfair_Display({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700', '800'],
  variable: '--font-playfair-display',
  display: 'swap',
});

const sourceSans3 = Source_Sans_3({
  subsets: ['latin'],
  weight: ['300', '400', '500', '600', '700'],
  variable: '--font-source-sans',
  display: 'swap',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-jetbrains-mono',
  display: 'swap',
});

const merriweather = Merriweather({
  subsets: ['latin'],
  weight: ['300', '400', '700', '900'],
  variable: '--font-merriweather',
  display: 'swap',
});

const crimsonText = Crimson_Text({
  subsets: ['latin'],
  weight: ['400', '600', '700'],
  variable: '--font-crimson-text',
  display: 'swap',
});

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'https://mrbekox.dev';

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: 'MrBekoX - Software Developer',
    template: '%s | MrBekoX Blog',
  },
  description: 'Yazılım geliştirme yolculuğumda öğrendiklerimi, aldığım teknik notları ve proje deneyimlerimi paylaştığım kişisel blog.',
  keywords: [
    'Berkay Kaplan',
    'MrBekoX',
    'backend development',
    'yazılım mimarisi',
    'software architecture',
    'AI agent',
    'artificial intelligence',
    'mikroservis',
    'microservices',
    'sistem tasarımı',
    'system design',
    'machine learning',
    '.NET',
    'ASP.NET Core',
    'C#',
    'Python',
    'onion architecture',
    'clean architecture',
    'CQRS',
    'domain driven design',
    'backend blog',
    'teknik blog',
    'software developer turkey',
  ],
  authors: [{ name: 'Berkay Kaplan', url: SITE_URL }],
  creator: 'Berkay Kaplan',
  publisher: 'Berkay Kaplan',
  formatDetection: {
    email: false,
    address: false,
    telephone: false,
  },
  openGraph: {
    type: 'website',
    locale: 'tr_TR',
    url: SITE_URL,
    title: 'MrBekoX - Software Developer',
    description: 'Yazılım geliştirme yolculuğumda öğrendiklerimi, aldığım teknik notları ve proje deneyimlerimi paylaştığım kişisel blog.',
    siteName: 'MrBekoX Blog',
    images: [
      {
        url: '/opengraph-image',
        width: 1200,
        height: 630,
        alt: 'MrBekoX Blog',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'MrBekoX | Software Developer',
    description: 'Yazılım geliştirme yolculuğumda öğrendiklerimi, aldığım teknik notları ve proje deneyimlerimi paylaştığım kişisel blog.',
    creator: '@mrbeko_',
    images: ['/opengraph-image'],
  },
  robots: {
    index: true,
    follow: true,
    nocache: false,
    googleBot: {
      index: true,
      follow: true,
      noimageindex: false,
      'max-video-preview': -1,
      'max-image-preview': 'large',
      'max-snippet': -1,
    },
  },
  alternates: {
    canonical: SITE_URL,
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="tr" suppressHydrationWarning>
      <head>
        {/* Enable View Transitions API for smooth page transitions (modern browsers) */}
        <meta name="view-transition" content="same-origin" />
        <OrganizationSchema />
        <WebsiteSchema />
        <PersonSchema />
      </head>
      <body className={`${playfairDisplay.variable} ${sourceSans3.variable} ${jetbrainsMono.variable} ${merriweather.variable} ${crimsonText.variable} antialiased min-h-screen flex flex-col`}>
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          <ErrorBoundary>
            <CacheSyncProvider>
              <Header />
              <main className="flex-1">{children}</main>
              <Footer />
              <Toaster position="top-right" />
            </CacheSyncProvider>
          </ErrorBoundary>
        </ThemeProvider>
      </body>
    </html>
  );
}
