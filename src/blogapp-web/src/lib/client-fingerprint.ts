let fingerprintPromise: Promise<string> | null = null;

function toHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer))
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('');
}

export async function getClientFingerprint(): Promise<string> {
  if (typeof window === 'undefined') {
    return 'server';
  }

  if (fingerprintPromise) {
    return fingerprintPromise;
  }

  fingerprintPromise = (async () => {
    const source = [
      navigator.userAgent,
      navigator.language,
      navigator.platform,
      Intl.DateTimeFormat().resolvedOptions().timeZone || 'unknown',
      `${window.screen?.width ?? 0}x${window.screen?.height ?? 0}`,
    ].join('|');

    try {
      const buffer = new TextEncoder().encode(source);
      const digest = await crypto.subtle.digest('SHA-256', buffer);
      return toHex(digest);
    } catch {
      return `fallback-${source}`;
    }
  })();

  return fingerprintPromise;
}
