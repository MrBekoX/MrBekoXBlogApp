/**
 * Commit edilmiş projection replay'i sayfalama + monoton (duplicate) filtre.
 *
 * Eski ArticleAgentPanel.ingestEvents döngüsünün saf çekirdeği:
 * - tek sayfa MaxPageSize=200; hasMore sürdükçe en fazla `maxPages` sayfa okunur
 *   (aşılırsa sonraki bildirim/yoklama imleçten kaldığı yerde sürer);
 * - event_sequence imleçten BÜYÜK olmayan olay (duplicate/geç) yok sayılır;
 *   sayfa içi sıra dışı/tekrarlı olay da imleci geri çeviremez;
 * - her yeni olay grubu imleç ilerletildikten sonra `onFresh`e verilir;
 * - `isStale()` true olursa (ör. yeni run başladı) sayfa UYGULANMADAN durulur.
 */

import type { AgentRunEvent, AgentRunEvents } from '@/types/agent';

export type ReplayOutcome = 'done' | 'stale' | 'page_cap';

export interface ReplayOptions {
  fetchPage: (after: number) => Promise<Pick<AgentRunEvents, 'events' | 'hasMore'>>;
  getCursor: () => number;
  setCursor: (sequence: number) => void;
  onFresh: (fresh: AgentRunEvent[]) => Promise<void> | void;
  isStale: () => boolean;
  maxPages: number;
}

/** İmleçten büyük ve kendinden öncekilerden kesin artan olaylar (monoton süzgeç). */
export function selectFreshEvents(events: AgentRunEvent[], cursor: number): AgentRunEvent[] {
  const fresh: AgentRunEvent[] = [];
  let last = cursor;
  for (const event of events) {
    if (typeof event.eventSequence !== 'number' || event.eventSequence <= last) continue;
    last = event.eventSequence;
    fresh.push(event);
  }
  return fresh;
}

export async function replayEventPages(options: ReplayOptions): Promise<ReplayOutcome> {
  for (let pageIndex = 0; pageIndex < options.maxPages; pageIndex += 1) {
    if (options.isStale()) return 'stale';
    const page = await options.fetchPage(options.getCursor());
    if (options.isStale()) return 'stale';

    const fresh = selectFreshEvents(page.events ?? [], options.getCursor());
    if (fresh.length > 0) {
      options.setCursor(fresh[fresh.length - 1].eventSequence);
      await options.onFresh(fresh);
    }

    if (!page.hasMore) return 'done';
  }
  return 'page_cap';
}
