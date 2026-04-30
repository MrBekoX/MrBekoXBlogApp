'use server';

import { revalidateTag, revalidatePath } from 'next/cache';

// Per-tag cooldown tracking
const lastRevalidations = new Map<string, number>();
const REVALIDATION_COOLDOWN_MS = 2000; // 2 seconds per tag

/**
 * Server action to revalidate Next.js Data Cache by tag.
 * Called from client when SignalR cache invalidation events are received.
 *
 * Uses revalidateTag() to directly invalidate the Data Cache entries
 * that server-api.ts fetches tag with (e.g. 'posts', 'categories', 'tags').
 * Also invalidates the Full Route Cache via revalidatePath so the next
 * navigation triggers a fresh server render.
 */
export async function revalidateCacheTag(tag: string): Promise<{ success: boolean }> {
  const now = Date.now();
  const lastTime = lastRevalidations.get(tag) ?? 0;
  if (now - lastTime < REVALIDATION_COOLDOWN_MS) {
    return { success: false };
  }
  lastRevalidations.set(tag, now);

  try {
    revalidateTag(tag, 'max');
    revalidatePath('/', 'layout');
  } catch {
    // Ignore revalidation errors
  }

  return { success: true };
}

/**
 * Revalidate all content-related caches.
 */
export async function revalidateAllContent(): Promise<{ success: boolean }> {
  try {
    revalidateTag('posts', 'max');
    revalidateTag('categories', 'max');
    revalidateTag('tags', 'max');
    revalidatePath('/', 'layout');
  } catch {
    // Ignore revalidation errors
  }

  return { success: true };
}

