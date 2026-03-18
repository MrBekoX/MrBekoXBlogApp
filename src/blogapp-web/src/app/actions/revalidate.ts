'use server';

import { revalidatePath, refresh } from 'next/cache';

/**
 * Server action to revalidate Next.js cache.
 * Called from client when SignalR cache invalidation events are received.
 *
 * With cache:'no-store' on fetches, there is no Data Cache to purge.
 * revalidatePath purges the Full Route Cache so the next navigation
 * triggers a fresh server render. refresh() signals the current client
 * to re-fetch the RSC payload immediately.
 */
export async function revalidateCacheTag(_tag: string): Promise<{ success: boolean }> {
  try {
    revalidatePath('/', 'layout');
  } catch {
    // Ignore revalidation errors
  }

  try {
    refresh();
  } catch {
    // Ignore refresh errors
  }

  return { success: true };
}

/**
 * Revalidate all content-related caches.
 */
export async function revalidateAllContent(): Promise<{ success: boolean }> {
  try {
    revalidatePath('/', 'layout');
  } catch {
    // Ignore revalidation errors
  }

  try {
    refresh();
  } catch {
    // Ignore refresh errors
  }

  return { success: true };
}

