import type { Metadata } from 'next';
import { Fira_Code, Playfair_Display, Source_Sans_3, JetBrains_Mono, Merriweather, Crimson_Text } from 'next/font/google';
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
} from '@/lib/site-config';
import './globals.css';

// IDE fonts
const firaCode = Fira_Code({
  subsets: ['latin'],
  weight: ['300', '400', '500', '600', '700'],
  variable: '--font-fira-code',
  display: 'swap',
});

// Legacy serif/sans fonts kept for admin console pages
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
        url: '/opengraph-image',
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
        {/* VT323 display font via CDN — next/font does not support this family */}
        <link
          href="https://fonts.googleapis.com/css2?family=VT323&display=swap"
          rel="stylesheet"
        />
        <OrganizationSchema />
        <WebsiteSchema />
        <PersonSchema />
      </head>
      <body
        className={`${firaCode.variable} ${playfairDisplay.variable} ${sourceSans3.variable} ${jetbrainsMono.variable} ${merriweather.variable} ${crimsonText.variable} antialiased min-h-screen`}
      >
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
