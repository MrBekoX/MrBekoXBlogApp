export function stripMarkdown(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, '')
    .replace(/`[^`]+`/g, '')
    .replace(/!\[.*?\]\(.*?\)/g, '')
    .replace(/\[(.+?)\]\(.*?\)/g, '$1')
    .replace(/#{1,6}\s+/g, '')
    .replace(/[*_~]+/g, '')
    .replace(/>\s+/g, '')
    .replace(/[-*]\s+/g, '')
    .replace(/\n{2,}/g, ' ')
    .replace(/\n/g, ' ')
    .trim();
}

export function plainDescription(text: string, maxLength = 160): string {
  const plain = stripMarkdown(text).replace(/\s+/g, ' ').trim();
  if (plain.length <= maxLength) return plain;
  if (maxLength <= 1) return plain.slice(0, maxLength);
  return `${plain.slice(0, maxLength - 1).trimEnd()}…`;
}

export function postSearchTitle(post: { metaTitle?: string | null; title: string }): string {
  return post.metaTitle?.trim() || post.title;
}

export function postSearchDescription(
  post: {
    metaDescription?: string | null;
    excerpt?: string | null;
    content?: string | null;
  },
  maxLength = 160,
): string {
  const preferred = post.metaDescription?.trim() || post.excerpt?.trim();
  return plainDescription(preferred || post.content || '', maxLength);
}

export function speakableSelectors(hasVisibleExcerpt: boolean): string[] {
  return hasVisibleExcerpt ? ['.post-title', '.post-excerpt'] : ['.post-title'];
}
