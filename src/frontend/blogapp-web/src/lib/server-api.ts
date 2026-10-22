import 'server-only';

import type {
  ApiResponse,
  BlogPost,
  Category,
  PaginatedResult,
  PaginationParams,
  Tag,
} from '@/types';

import type { AuthorProfile } from '@/types/profile';

import { SERVER_API_URL } from '@/lib/env.server';
import { normalizeAuthorProfile } from '@/lib/author-profile';

const API_BASE_URL = SERVER_API_URL;

function buildQueryString(params?: Record<string, unknown>): string {
  if (!params) return '';

  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      searchParams.append(key, String(value));
    }
  });

  const queryString = searchParams.toString();
  return queryString ? `?${queryString}` : '';
}

async function serverFetch<T>(endpoint: string): Promise<T | null> {
  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(5000),
    });

    if (!response.ok) {
      console.error(`[SSR] ${endpoint} failed: ${response.status}`);
      return null;
    }

    const data: ApiResponse<T> = await response.json();
    return data.data ?? null;
  } catch (error) {
    console.error(`[SSR] ${endpoint} error:`, error instanceof Error ? error.message : 'Unknown');
    return null;
  }
}

export interface FetchPostsParams extends PaginationParams {
  status?: string;
  categoryId?: string;
  tagId?: string;
  search?: string;
  sortBy?: string;
  sortDescending?: boolean;
}

export async function fetchPosts(
  params?: FetchPostsParams
): Promise<PaginatedResult<BlogPost> | null> {
  const apiParams = params ? {
    ...params,
    searchTerm: params.search,
    search: undefined,
  } : undefined;

  const queryString = buildQueryString(apiParams);

  return serverFetch<PaginatedResult<BlogPost>>(`/posts${queryString}`);
}

export async function fetchPostBySlug(slug: string): Promise<BlogPost | null> {
  return serverFetch<BlogPost>(`/posts/slug/${encodeURIComponent(slug)}`);
}

export async function fetchPostById(id: string): Promise<BlogPost | null> {
  return serverFetch<BlogPost>(`/posts/${encodeURIComponent(id)}`);
}

export async function fetchCategories(
  excludeEmptyCategories?: boolean
): Promise<Category[] | null> {
  const queryString = buildQueryString({ excludeEmptyCategories });

  return serverFetch<Category[]>(`/categories${queryString}`);
}

export async function fetchCategoryById(id: string): Promise<Category | null> {
  return serverFetch<Category>(`/categories/${encodeURIComponent(id)}`);
}

export async function fetchTags(includeEmpty?: boolean): Promise<Tag[] | null> {
  const queryString = buildQueryString({ includeEmpty });

  return serverFetch<Tag[]>(`/tags${queryString}`);
}

export async function fetchTagById(id: string): Promise<Tag | null> {
  return serverFetch<Tag>(`/tags/${encodeURIComponent(id)}`);
}

/**
 * Yayımlanmış yazar profili (/about). Backend aktif + public + hash doğrulanmış
 * profili döner; kullanılamıyorsa (503/ağ/şema) null → sayfa biyografi gövdesi
 * göstermez. serverFetch `cache: 'no-store'` kullanır: eski profil gövdesi
 * önbellekten sunulmaz (A37).
 */
export async function fetchAuthorProfile(): Promise<AuthorProfile | null> {
  const raw = await serverFetch<unknown>('/profile');
  return normalizeAuthorProfile(raw);
}
