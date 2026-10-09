// =============================================================================
// Merkezi site konfigurasyonu — tum hardcoded degerler buradan okunur
// Her deger NEXT_PUBLIC_* env var ile override edilebilir
// =============================================================================

// --- Site ---
export const SITE_NAME = process.env.NEXT_PUBLIC_SITE_NAME || 'MrBekoX';
export const SITE_TITLE = process.env.NEXT_PUBLIC_SITE_TITLE || 'MrBekoX - Software Developer';
export const SITE_TITLE_TEMPLATE = process.env.NEXT_PUBLIC_SITE_TITLE_TEMPLATE || '%s | MrBekoX Blog';
export const SITE_TAGLINE = process.env.NEXT_PUBLIC_SITE_TAGLINE || 'Software Developer';
export const SITE_DESCRIPTION =
  process.env.NEXT_PUBLIC_SITE_DESCRIPTION ||
  'Yazılım geliştirme yolculuğumda öğrendiklerimi, aldığım teknik notları ve proje deneyimlerimi paylaştığım kişisel blog.';
export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'https://mrbekox.dev';
export const SITE_LOCALE = process.env.NEXT_PUBLIC_SITE_LOCALE || 'tr_TR';

// --- Author / Person ---
export const AUTHOR_NAME = process.env.NEXT_PUBLIC_AUTHOR_NAME || 'Sample Author';
export const AUTHOR_JOB_TITLE = process.env.NEXT_PUBLIC_AUTHOR_JOB_TITLE || 'Software Developer';
export const AUTHOR_DESCRIPTION =
  process.env.NEXT_PUBLIC_AUTHOR_DESCRIPTION ||
  'Backend geliştirme, yazılım mimarisi ve AI teknolojileri üzerine uzmanlaşmış yazılım geliştirici.';

// --- Social URLs ---
export const GITHUB_URL = process.env.NEXT_PUBLIC_GITHUB_URL || 'https://example.invalid/author';
export const TWITTER_URL = process.env.NEXT_PUBLIC_TWITTER_URL || 'https://example.invalid/social';
export const LINKEDIN_URL =
  process.env.NEXT_PUBLIC_LINKEDIN_URL || 'https://example.invalid/author';
export const TWITTER_HANDLE = process.env.NEXT_PUBLIC_TWITTER_HANDLE || '@sample';

export const SOCIAL_URLS = [GITHUB_URL, TWITTER_URL, LINKEDIN_URL];

// --- Timeouts (ms) ---
export const API_TIMEOUT_MS = Number(process.env.NEXT_PUBLIC_API_TIMEOUT_MS || '15000');
export const REDIRECT_COOLDOWN_MS = Number(process.env.NEXT_PUBLIC_REDIRECT_COOLDOWN_MS || '10000');

// --- Limits ---
export const MAX_FILE_SIZE_BYTES = Number(process.env.NEXT_PUBLIC_MAX_FILE_SIZE_BYTES || String(10 * 1024 * 1024));
export const POST_CONTENT_MAX_LENGTH = Number(process.env.NEXT_PUBLIC_POST_CONTENT_MAX_LENGTH || '500000');

// --- SEO Keywords ---
export const SITE_KEYWORDS: string[] = (process.env.NEXT_PUBLIC_SITE_KEYWORDS || [
  'Sample Author',
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
].join(','))
  .split(',')
  .map((k) => k.trim())
  .filter(Boolean);
