'use client';

import * as React from 'react';
import { ThemeProvider as NextThemesProvider } from 'next-themes';
import { useDocumentNonce } from '@/components/security/nonce-provider';

type ThemeProviderProps = React.ComponentProps<typeof NextThemesProvider>;

export function ThemeProvider({ children, ...props }: ThemeProviderProps) {
  const nonce = useDocumentNonce() ?? props.nonce;
  return <NextThemesProvider {...props} nonce={nonce}>{children}</NextThemesProvider>;
}

