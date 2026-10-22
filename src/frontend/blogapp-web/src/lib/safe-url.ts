/**
 * Paylaşılan URL güvenlik yardımcıları (saf; tarayıcı/sunucu fark etmez).
 *
 * - `sanitizeUrl`: makale markdown'ı (MarkdownRenderer) için mevcut kural —
 *   javascript:/data:/vbscript:/file: şemalarını eler; http(s), göreli ve
 *   şemasız yolları geçirir. Davranış markdown-renderer.tsx'teki eski yerel
 *   fonksiyonla aynıdır; tek fark bozuk yüzde kodlamasında (decodeURIComponent
 *   URIError) render'ı çökertmek yerine `undefined` dönmesidir.
 * - `safeExternalHttpUrl`: yalnız mutlak http/https (kimlik bilgisi içermeyen)
 *   URL'leri kabul eder; agent kaynak kartı ve iletişim kanalları için.
 * - `safeChatLinkHref`: agent sohbet/profil markdown linkleri için daha dar
 *   kural: http(s) mutlak, kök-göreli ("/..." ama "//" değil) veya "#..." anchor.
 */

const DANGEROUS_PROTOCOLS = ['javascript:', 'data:', 'vbscript:', 'file:'];

/**
 * XSS Protection: Validates URL to prevent javascript: and data: URIs
 * Only allows http:, https:, and relative paths
 */
export function sanitizeUrl(url: string | undefined): string | undefined {
  if (!url) return undefined;

  // Decode URL to catch encoded attacks
  let decodedUrl: string;
  try {
    decodedUrl = decodeURIComponent(url).trim().toLowerCase();
  } catch {
    return undefined; // malformed percent-encoding: güvenli tarafta kal
  }

  // Block dangerous protocols
  for (const protocol of DANGEROUS_PROTOCOLS) {
    if (decodedUrl.startsWith(protocol)) {
      return undefined;
    }
  }

  // Allow http, https, and relative paths
  if (
    url.startsWith('http://') ||
    url.startsWith('https://') ||
    url.startsWith('/') ||
    url.startsWith('#') ||
    url.startsWith('./') ||
    url.startsWith('../')
  ) {
    return url;
  }

  // For other relative URLs (e.g., "image.png"), allow them
  if (!url.includes(':')) {
    return url;
  }

  return undefined;
}

/** Kontrol karakteri / boşluk içeren URL'ler (gizlenmiş şema hileleri) reddedilir. */
export function hasControlOrSpace(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code <= 0x20 || (code >= 0x7f && code <= 0x9f)) return true;
  }
  return false;
}

/**
 * Yalnız mutlak http:// veya https:// URL. Kimlik bilgisi (user:pass@) taşıyan,
 * boşluk/kontrol karakterli veya ayrıştırılamayan URL reddedilir. Dönen değer
 * URL ayrıştırıcısının normalize ettiği href'tir.
 */
export function safeExternalHttpUrl(url: string | null | undefined): string | null {
  if (typeof url !== 'string') return null;
  const candidate = url.trim();
  if (!candidate || hasControlOrSpace(candidate)) return null;
  if (!/^https?:\/\//i.test(candidate)) return null;

  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    return null;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
  if (!parsed.hostname || parsed.username || parsed.password) return null;
  return parsed.href;
}

export interface SafeLinkHref {
  href: string;
  /** Mutlak http(s) bağlantı: yeni sekme + rel="noopener noreferrer nofollow". */
  external: boolean;
}

/**
 * Agent sohbeti ve profil gövdesindeki markdown linkleri için izinli href.
 * İzin: http(s) mutlak, "/" ile başlayan kök-göreli yol ("//host" protokol-göreli
 * ve "/\\" ters-eğik hileleri hariç) ve "#anchor". Diğer her şey (javascript:,
 * data:, mailto:, göreli "foo", protokol-göreli) null → link render edilmez.
 */
export function safeChatLinkHref(href: string | null | undefined): SafeLinkHref | null {
  if (typeof href !== 'string') return null;
  const candidate = href.trim();
  if (!candidate || hasControlOrSpace(candidate)) return null;

  if (candidate.startsWith('#')) {
    return { href: candidate, external: false };
  }

  if (candidate.startsWith('/')) {
    if (candidate.startsWith('//') || candidate.startsWith('/\\')) return null;
    return { href: candidate, external: false };
  }

  const external = safeExternalHttpUrl(candidate);
  return external ? { href: external, external: true } : null;
}
