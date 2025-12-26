import type { Metadata } from 'next';
import { Header } from '@/components/layout/header';
import { Footer } from '@/components/layout/footer';
import { Toaster } from '@/components/ui/sonner';
import { ThemeProvider } from '@/components/theme-provider';
import './globals.css';

export const metadata: Metadata = {
  title: {
    default: 'MrBekoX | Kişisel Blog',
    template: '%s | MrBekoX Blog',
  },
  description: 'Yazılım, teknoloji ve yaşam üzerine düşünceler. Kod yazarken öğrendiklerimi, deneyimlerimi ve projelerimi paylaştığım kişisel blog.',
  keywords: ['blog', 'yazılım', 'teknoloji', 'programlama', 'web geliştirme', 'kişisel blog', 'MrBekoX'],
  authors: [{ name: 'MrBekoX' }],
  creator: 'MrBekoX',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="tr" suppressHydrationWarning>
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500;600;700;800&family=Source+Sans+3:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="antialiased min-h-screen flex flex-col">
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          <Header />
          <main className="flex-1">{children}</main>
          <Footer />
          <Toaster position="top-right" />
        </ThemeProvider>
      </body>
    </html>
  );
}
