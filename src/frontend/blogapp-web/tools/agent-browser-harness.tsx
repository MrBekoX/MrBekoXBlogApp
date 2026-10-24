'use client';

/** Real React acceptance surface. Only the backend is replaced by a loopback fixture. */
import { useCallback, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { useAgentSession, type AgentSubmitRequest } from '../src/hooks/use-agent-session';
import { AgentChatMarkdown } from '../src/components/agent/agent-chat-markdown';
import { buildAgentRequest } from '../src/lib/agent/topic';
import { validateRestoredRun } from '../src/lib/agent/session-model';
import type { AgentRunStatus } from '../src/types/agent';

declare global {
  interface Window {
    agentAcceptance?: {
      phase: string | null;
      active: boolean;
      provisional: boolean;
      verificationUnavailable: boolean;
      answer: string | null;
      announcement: string;
      channel: string;
      submit: () => Promise<boolean>;
      retry: () => Promise<boolean>;
      checkFinal: () => Promise<void>;
    };
  }
}

function AcceptancePanel() {
  const name = new URLSearchParams(location.search).get('case') ?? 'normal';
  const buildRequest = useCallback((input: AgentSubmitRequest) => buildAgentRequest({ ...input,
    language: 'en', topic: 'auto', modePreference: input.modePreference ?? 'auto' }), []);
  const validate = useCallback((status: AgentRunStatus, id: string) =>
    validateRestoredRun(status, id, { topic: 'auto' }).ok, []);
  const session = useAgentSession({ storageKey: `acceptance-${name}`, topic: 'auto', lang: 'en',
    buildRequest, validateRestoredRun: validate, streamLiveAnswer: true });
  const answer = session.activeTurn?.status?.result?.answer ?? session.activeTurn?.status?.result?.report ?? null;
  useEffect(() => {
    window.agentAcceptance = { phase: session.activeTurn?.phase ?? null, active: session.isRunActive,
      provisional: session.activeIsProvisional, answer, announcement: session.announcement, channel: session.channel,
      verificationUnavailable: session.finalVerificationUnavailable,
      submit: () => session.submit('Please explain this article.', false), retry: session.retryLast,
      checkFinal: session.checkFinalResult };
  });
  return <main>
    <button id="submit" disabled={session.isRunActive} onClick={() => void session.submit('Please explain this article.', false)}>Ask</button>
    <button id="retry" disabled={session.isRunActive} onClick={() => void session.retryLast()}>Retry</button>
    <p id="phase">{session.activeTurn?.phase ?? 'idle'}</p>
    <p id="provisional">{session.activeIsProvisional ? session.t.provisionalTerminalHint : ''}</p>
    <p id="unconfirmed">{session.finalVerificationUnavailable ? session.t.finalVerificationUnavailable : ''}</p>
    <p role="status">{session.announcement}</p>
    <section id="answer">{answer ? <AgentChatMarkdown content={answer} /> : null}</section>
  </main>;
}

createRoot(document.getElementById('root')!).render(<AcceptancePanel />);
