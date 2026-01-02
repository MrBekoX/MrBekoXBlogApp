import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function getImageUrl(url?: string | null): string | undefined {
  if (!url) return undefined;
  if (url.startsWith('http://') || url.startsWith('https://')) return url;
  
  // Get API URL (e.g. https://domain.com/api/v1)
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5116/api/v1';
  
  // Remove /api/v1 suffix to get base domain
  const baseUrl = apiUrl.replace(/\/api\/v1\/?$/, '');
  
  // Handle leading slash in url
  const cleanUrl = url.startsWith('/') ? url : `/${url}`;
  
  return `${baseUrl}${cleanUrl}`;
}
