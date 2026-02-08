import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const PROTECTED_PATHS = ['/mrbekox-console/dashboard'];

export default function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Check if the path requires authentication
  const isProtected = PROTECTED_PATHS.some(path => pathname.startsWith(path));

  if (isProtected) {
    // Check for auth cookie (HttpOnly cookie set by backend)
    // Backend uses 'accessToken' cookie name
    const accessToken = request.cookies.get('accessToken');

    if (!accessToken) {
      const loginUrl = new URL('/mrbekox-console', request.url);
      loginUrl.searchParams.set('redirect', pathname);
      return NextResponse.redirect(loginUrl);
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/mrbekox-console/dashboard/:path*'],
};
