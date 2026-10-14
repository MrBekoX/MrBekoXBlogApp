import type { Metadata } from 'next';
import { Toaster } from '@/components/ui/sonner';
import { ThemeProvider } from '@/components/theme-provider';
import { CacheSyncProvider } from '@/components/cache-sync-provider';
import { AuthSyncProvider } from '@/components/auth/auth-sync-provider';
import { ErrorBoundary } from '@/components/error-boundary';
import { OrganizationSchema } from '@/components/seo/organization-schema';
import { WebsiteSchema } from '@/components/seo/website-schema';
import { PersonSchema } from '@/components/seo/person-schema';
import {
  SITE_URL,
  SITE_TITLE,
  SITE_TITLE_TEMPLATE,
  SITE_DESCRIPTION,
  SITE_KEYWORDS,
  SITE_NAME,
  SITE_LOCALE,
  AUTHOR_NAME,
  TWITTER_HANDLE,
  OG_IMAGE_PATH,
} from '@/lib/site-config';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: SITE_TITLE,
    template: SITE_TITLE_TEMPLATE,
  },
  description: SITE_DESCRIPTION,
  keywords: SITE_KEYWORDS,
  authors: [{ name: AUTHOR_NAME, url: SITE_URL }],
  creator: AUTHOR_NAME,
  publisher: AUTHOR_NAME,
  formatDetection: {
    email: false,
    address: false,
    telephone: false,
  },
  openGraph: {
    type: 'website',
    locale: SITE_LOCALE,
    url: SITE_URL,
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    siteName: `${SITE_NAME} Blog`,
    images: [
      {
        url: OG_IMAGE_PATH,
        width: 1200,
        height: 630,
        alt: `${SITE_NAME} Blog`,
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: `${SITE_NAME} | ${AUTHOR_NAME}`,
    description: SITE_DESCRIPTION,
    creator: TWITTER_HANDLE,
    images: [OG_IMAGE_PATH],
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
        {/* Google Fonts via CDN at runtime — next/font/google downloads at build time and
            breaks offline builds. Family names are declared as CSS vars in globals.css;
            local fallback stacks apply when the CDN is unreachable. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Crimson+Text:wght@400;600;700&family=Fira+Code:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Merriweather:wght@300;400;700;900&family=Playfair+Display:wght@400;500;600;700;800&family=Source+Sans+3:wght@300;400;500;600;700&family=VT323&display=swap"
          rel="stylesheet"
        />
        <link rel="describedby" href={`${SITE_URL}/llms.txt`} type="text/plain" />
        <OrganizationSchema />
        <WebsiteSchema />
        <PersonSchema />
      </head>
      <body className="antialiased min-h-screen">
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          <ErrorBoundary>
            <CacheSyncProvider debug={process.env.NODE_ENV === 'development'}>
              <AuthSyncProvider>
                {children}
              </AuthSyncProvider>
              <Toaster position="top-right" />
            </CacheSyncProvider>
          </ErrorBoundary>
        </ThemeProvider>
      </body>
    </html>
  );
}
