'use server';

import { revalidateTag } from 'next/cache';

/**
 * Server action to revalidate Next.js cache by tag.
 * Called from client when SignalR cache invalidation events are received.
 */
export async function revalidateCacheTag(tag: string): Promise<{ success: boolean }> {
  try {
    // Use appropriate profile based on tag
    const profile = tag.includes('posts') ? 'posts' : 
                   tag.includes('categories') ? 'categories' : 
                   tag.includes('tags') ? 'tags' : 'default';
    
    revalidateTag(tag, profile);
    return { success: true };
  } catch (error) {
    console.error(`Failed to revalidate tag ${tag}:`, error);
    return { success: false };
  }
}

/**
 * Revalidate all content-related cache tags.
 * Use this for broad invalidation events.
 */
export async function revalidateAllContent(): Promise<{ success: boolean }> {
  try {
    revalidateTag('posts', 'posts');
    revalidateTag('categories', 'categories');
    revalidateTag('tags', 'tags');
    return { success: true };
  } catch (error) {
    console.error('Failed to revalidate all content:', error);
    return { success: false };
  }
}
