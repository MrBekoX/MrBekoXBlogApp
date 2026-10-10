import type { Category } from '@/types';

interface PostCategorySource {
  category?: Category | null;
  categories?: Category[] | null;
}

export function postCategories(post: PostCategorySource): Category[] {
  if (post.categories && post.categories.length > 0) return post.categories;
  if (post.category) return [post.category];
  return [];
}
