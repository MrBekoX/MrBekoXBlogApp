import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
import { BASE_URL } from '@/lib/env'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function getImageUrl(url?: string | null): string | undefined {
  if (!url) return undefined;
  if (url.startsWith('http://') || url.startsWith('https://')) return url;
  
  // Handle leading slash in url
  const cleanUrl = url.startsWith('/') ? url : `/${url}`;
  
  return `${BASE_URL}${cleanUrl}`;
}
