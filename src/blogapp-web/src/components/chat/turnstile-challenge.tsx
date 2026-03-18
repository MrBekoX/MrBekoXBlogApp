'use client';

import { useEffect, useRef, useState } from 'react';
import Script from 'next/script';

declare global {
  interface Window {
    turnstile?: {
      render: (container: HTMLElement, options: Record<string, unknown>) => string;
      remove: (widgetId: string) => void;
    };
  }
}

interface TurnstileChallengeProps {
  siteKey: string;
  action?: string;
  challengeKey: number;
  onSolved: (token: string) => void;
  onError?: (message: string) => void;
}

export function TurnstileChallenge({
  siteKey,
  action = 'chat',
  challengeKey,
  onSolved,
  onError,
}: TurnstileChallengeProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const [scriptReady, setScriptReady] = useState(false);

  useEffect(() => {
    if (!scriptReady || !siteKey || !containerRef.current || !window.turnstile) {
      return;
    }

    if (widgetIdRef.current) {
      window.turnstile.remove(widgetIdRef.current);
      widgetIdRef.current = null;
    }

    widgetIdRef.current = window.turnstile.render(containerRef.current, {
      sitekey: siteKey,
      action,
      callback: (token: unknown) => {
        if (typeof token === 'string' && token.length > 0) {
          onSolved(token);
        }
      },
      'expired-callback': () => {
        onError?.('Human verification expired. Please try again.');
      },
      'error-callback': () => {
        onError?.('Human verification failed. Please try again.');
      },
      theme: 'dark',
    });

    return () => {
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }
    };
  }, [action, challengeKey, onError, onSolved, scriptReady, siteKey]);

  if (!siteKey) {
    return (
      <div className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
        Human verification is not configured for this environment.
      </div>
    );
  }

  return (
    <>
      <Script
        src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"
        strategy="afterInteractive"
        onLoad={() => setScriptReady(true)}
      />
      <div className="rounded border border-ide-border bg-ide-bg/80 px-3 py-3">
        <div ref={containerRef} className="min-h-[65px]" />
      </div>
    </>
  );
}
