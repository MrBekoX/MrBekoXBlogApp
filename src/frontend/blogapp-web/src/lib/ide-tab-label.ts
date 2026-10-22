/** IDE sekme etiketi: rota → sahte dosya adı (saf; ide-tab-bar kullanır). */
export function getTabLabel(pathname: string): string {
  if (pathname === '/') return 'how-to-center.md';
  if (pathname === '/posts') return 'posts-list.md';
  if (pathname === '/about' || pathname.startsWith('/about/')) return 'about.md';
  if (pathname.startsWith('/posts/')) {
    const slug = pathname.replace('/posts/', '').split('/')[0];
    return `${slug}.md`;
  }
  return 'index.md';
}
