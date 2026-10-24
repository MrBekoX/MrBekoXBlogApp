'use client';

import * as React from 'react';
import { setNonce } from 'get-nonce';

const NonceContext = React.createContext<string | undefined>(undefined);

/** RSC navigations get fresh request headers, but retain the current document's CSP nonce. */
export function NonceProvider({ nonce, children }: { nonce?: string; children: React.ReactNode }) {
  const [documentNonce] = React.useState(nonce);
  React.useInsertionEffect(() => {
    if (!documentNonce) return;
    // Client-only library configuration: never share a nonce through server globals.
    setNonce(documentNonce);
    document.querySelector('meta[property="csp-nonce"]')?.setAttribute('content', documentNonce);
  }, [documentNonce, nonce]);
  return <NonceContext.Provider value={documentNonce}>{children}</NonceContext.Provider>;
}

export function useDocumentNonce() {
  return React.useContext(NonceContext);
}
