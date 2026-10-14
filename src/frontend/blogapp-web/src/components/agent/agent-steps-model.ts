/**
 * Canlı işlem adımları modeli (saf fonksiyonlar; bileşenden bağımsız test edilebilir).
 *
 * Kaynak yalnız GERÇEK olaylardır: commit edilmiş projection replay'i
 * (GET /api/v1/agent/runs/{runId}/events). Burada sahte adım üretimi,
 * zamanlayıcıyla adım yaratma YOKTUR — zamanlayıcı yalnız GELMİŞ bir adımın
 * "çalışıyor" süresini (elapsed) ekranda güncellemek için kullanılır.
 *
 * kind sözleşmesi (entegrasyon sahibi tanımı):
 * - progressed olayında payload.kind (common.schema.json progress_kind enum);
 * - terminal olaylarda messageType son ekinden türet:
 *     agent.run.completed → completed, agent.run.failed → failed,
 *     agent.run.cancelled → cancelled, agent.run.partially_completed → partial;
 * - agent.action.proposed → action_proposed;
 * - agent.run.needs_input → needs_input (B9: çalışma TERMINAL DEĞİLDİR, ek
 *   girdi bekler; GET 'Accepted' döner — resume ile devam edilir).
 * Alan endpoint'e henüz eklenmemişse (eski kayıt) kind absent olabilir; bu
 * durumda olay GERÇEKTİR ama alt türü bilinmiyordur → genel 'progress' adımı.
 */

import type { AgentRunEvent } from '@/types/agent';

/** Bilinen kind kümesi (sözleşme: common.schema.json progress_kind + terminal türevleri). */
export const AGENT_STEP_KINDS = [
  'run_started',
  'mode_selected',
  'article_context_ready',
  'run_resumed',
  'retrieval_started',
  'retrieval_completed',
  'research_started',
  'research_round_completed',
  'generation_started',
  'generation_completed',
  'validation_completed',
  'action_proposed',
  'needs_input',
  'tool_error', // progressed payload'tan: tekil dış araç hatası (akış kısmi yolda sürer)
  'completed',
  'failed',
  'cancelled',
  'partial',
  // NOT: 'generation_delta' bu listede BİLİNÇLİ OLARAK YOKTUR — akış parçası
  // adım değildir; foldDeltaText ile canlı metne katılır (aşağıda).
] as const;

export type AgentStepKind = (typeof AGENT_STEP_KINDS)[number] | 'progress';

/** Terminal + proposal/needs_input olaylarında messageType → kind (kablo adları: AgentMessageTypeRegistry). */
const KIND_BY_MESSAGE_TYPE: Record<string, AgentStepKind> = {
  'agent.run.completed': 'completed',
  'agent.run.partially_completed': 'partial',
  'agent.run.failed': 'failed',
  'agent.run.cancelled': 'cancelled',
  'agent.run.needs_input': 'needs_input',
  'agent.action.proposed': 'action_proposed',
};

const KNOWN_KINDS = new Set<string>(AGENT_STEP_KINDS);

/** Terminal olay türleri (adım listesini kapatır). */
export function isTerminalKind(kind: string): boolean {
  return kind === 'completed' || kind === 'partial' || kind === 'failed' || kind === 'cancelled';
}

/** Çalışmayı TERMINAL olarak KAPATMAYAN bekleme türü: needs_input (B9) —
 * "çalışıyor" nabzı durmalı ama besteci/kapatma terminal davranışı görmez. */
export function isWaitingInputKind(kind: string): boolean {
  return kind === 'needs_input';
}

/**
 * Olayın kind'ını sözlükten türetir: öncelik endpoint'in verdiği `kind`;
 * yoksa messageType'tan (noktalı kablo adı ya da AgentRunCompletedV1 biçimli
 * sınıf adı — ikisi de son ek kuralıyla çözülür). Çözülemezse null.
 */
export function deriveEventKind(event: Pick<AgentRunEvent, 'kind' | 'messageType'>): AgentStepKind | null {
  // Akış parçası (generation_delta) ADIM DEĞİLDİR: null döner — buildAgentSteps
  // imleci ilerletir ama adım üretmez; parça foldDeltaText ile metne katılır.
  if (event.kind === 'generation_delta') return null;

  if (event.kind && KNOWN_KINDS.has(event.kind)) return event.kind as AgentStepKind;

  const direct = KIND_BY_MESSAGE_TYPE[event.messageType];
  if (direct) return direct;

  // Son segment: "agent.run.partially_completed" → "partially_completed",
  // "AgentRunPartiallyCompletedV1" → "partiallycompleted" (V1 eki atılır).
  const tail = (event.messageType.split('.').pop() ?? event.messageType)
    .replace(/^AgentRun/i, '')
    .replace(/v1$/i, '')
    .toLowerCase();
  if (tail === 'partiallycompleted' || tail === 'partially_completed') return 'partial';
  if (tail === 'completed' || tail === 'failed' || tail === 'cancelled') return tail;
  if (tail === 'needs_input' || tail === 'needsinput') return 'needs_input';
  if (tail === 'proposed' || tail === 'actionproposed') return 'action_proposed';
  if (tail === 'progressed') return 'progress'; // kind'ı gelmemiş progressed kaydı
  return null;
}

/** Tamamlanma türündeki adımın başlangıç eşi (süre = occurredAt farkı). */
const START_OF_COMPLETED: Partial<Record<AgentStepKind, AgentStepKind>> = {
  retrieval_completed: 'retrieval_started',
  research_round_completed: 'research_started',
  generation_completed: 'generation_started',
};

/** Tek adımın görünüm modeli. */
export interface AgentStepVM {
  /** Olay event_sequence'i (listeleme ve monotonluk anahtarı). */
  sequence: number;
  kind: AgentStepKind;
  occurredAt: string;
  /** Eşli tamamlama adımıysa başlangıç olayının zamanı (süre hesabı için). */
  startedAt?: string;
  /** Gelen mesaj (progressed inbox.ProgressMessage — kullanıcı-dostu cümle). */
  message?: string | null;
  /** Gelen detail sözlüğü (küratörlü kullanıcı-dostu alanlar). */
  detail?: Record<string, string> | null;
}

/**
 * Olay listesinden (event_sequence sıralı GELMİŞ olaylar) adım listesi kurar.
 * Kind türetilemeyen olaylar ATLANMAZ: 'progress' genel adımı olarak alınır
 * (olay gerçek; etiketi genel). Sıra olayların geliş sırasıdır — paralel
 * worker olayları tek listede, sahte paralellik gösterilmeden akar.
 *
 * MONOTON FİLTRE (model sözleşmesi): event_sequence'i son işlenen diziden
 * BÜYÜK olmayan olay (aynı sequence'in tekrarı ya da geç/stale replay)
 * YOK SAYILIR — duplicate listeyle çağrı buildAgentSteps idempotenttir ve
 * adım çoğaltmaz (bileşen imleci ek güvencedir, tek başına yeterli değildir).
 *
 * Eşli tamamlama adımı (ör. research_round_completed) en yakın eşleşen
 * başlangıca/aynı-tür önceki adıma bağlanır: agent_core'da research_started
 * BİR KEZ, research_round_completed HER TUR için bir kez yayınlanır
 * (research/nodes.py:279 ve :527) — çok turlu akışta 2. tur kendi penceresini
 * önceki turun tamamlanma zamanından alır.
 */
export function buildAgentSteps(events: AgentRunEvent[]): AgentStepVM[] {
  const steps: AgentStepVM[] = [];
  const consumedStarts = new Set<number>();
  // B5 sözleşmesi: event_sequence 1'den monoton artar; <= son görülen = duplicate/geç.
  let lastSequence = 0;

  for (const event of events) {
    if (event.eventSequence <= lastSequence) continue; // duplicate/geç olay: adım çoğaltamaz
    lastSequence = event.eventSequence;

    const kind = deriveEventKind(event);
    if (!kind) continue; // adım gösterilemeyen idari olay (ör. agent.run.accepted)

    const step: AgentStepVM = {
      sequence: event.eventSequence,
      kind,
      occurredAt: event.occurredAt,
      message: event.message ?? undefined,
      detail: event.detail ?? undefined,
    };

    // Eşli tamamlama adımı: en yakın eşleşen (başlangıç türü ya da aynı tür),
    // henüz başka bir tamamlamaya bağlanmamış adımı bul.
    const startKind = START_OF_COMPLETED[kind];
    if (startKind) {
      for (let i = steps.length - 1; i >= 0; i -= 1) {
        const candidate = steps[i];
        if ((candidate.kind === startKind || candidate.kind === kind) && !consumedStarts.has(i)) {
          if (candidate.startedAt === undefined) candidate.startedAt = candidate.occurredAt;
          step.startedAt = candidate.occurredAt;
          consumedStarts.add(i);
          break;
        }
      }
    }

    steps.push(step);
  }

  return steps;
}

/**
 * Canlı yanıt metni: kind'ı 'generation_delta' olan olayların message
 * parçalarını liste sırasına göre birleştirir (araya başka olay girmiş olsa da
 * parça sırası korunur — broker parçaları AgentRunProgressedV1.message ile
 * sıralı akıtır; token-başına mesaj yoktur, birleştirilmiş chunk'tır).
 *
 * Monoton filtre buildAgentSteps ile AYNI sözleşmedir: event_sequence'i
 * kendisinden önce görülenden BÜYÜK olmayan olay (duplicate ya da geç/stale
 * replay) YOK SAYILIR — duplicate listeyle çağrı foldDeltaText idempotenttir
 * ve metni değiştirmez. Delta olayı yoksa boş string döner; normal adım
 * olaylarının message'ları metne KARIŞMAZ.
 */
export function foldDeltaText(events: AgentRunEvent[]): string {
  let text = '';
  // B5 sözleşmesi: event_sequence 1'den monoton artar; <= son görülen = duplicate/geç.
  let lastSequence = 0;

  for (const event of events) {
    if (event.eventSequence <= lastSequence) continue; // duplicate/geç olay: metni değiştiremez
    lastSequence = event.eventSequence;

    if (event.kind !== 'generation_delta') continue;
    if (event.message) text += event.message;
  }

  return text;
}

/** ms → "42 sn" / "1dk 05 sn" (saniye hassasiyeti yeterli). */
export function formatDuration(durationMs: number, lang: 'tr' | 'en'): string {
  const totalSeconds = Math.max(0, Math.floor(durationMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const secUnit = lang === 'tr' ? 'sn' : 's';
  const minUnit = lang === 'tr' ? 'dk' : 'm';
  if (minutes <= 0) return `${totalSeconds} ${secUnit}`;
  return `${minutes} ${minUnit} ${String(seconds).padStart(2, '0')} ${secUnit}`;
}

/** detail sözlüğünden güvenli kısa özet satırları (değerler küratörlü düz metin; React kaçışlar). */
export function summarizeDetail(
  detail: Record<string, string> | null | undefined,
  maxEntries = 3,
): Array<{ key: string; value: string }> {
  if (!detail) return [];
  return Object.entries(detail)
    .slice(0, maxEntries)
    .map(([key, value]) => ({
      key: key.replace(/_/g, ' ').trim(),
      value: value.length > 140 ? `${value.slice(0, 137)}…` : value,
    }))
    .filter((entry) => entry.value.length > 0);
}

/** Bir adımın sabit (yerleşmiş) süresi: eşli tamamlama adımı = start→completed
 * occurredAt farkı; diğer adımlar = kendi zamanından SONRAKİ adımın zamanına
 * kadar geçen gerçek pencere (iki gerçek olay zaman damgası arası; tahmin YOK).
 * Son adım ve pencere yoksa null — canlı elapsed alanına bırakılır. */
export function settledStepDurationMs(
  step: AgentStepVM,
  nextStep: AgentStepVM | undefined,
): number | null {
  const occurredMs = Date.parse(step.occurredAt);
  if (!Number.isFinite(occurredMs)) return null;

  if (step.startedAt) {
    const startedMs = Date.parse(step.startedAt);
    if (Number.isFinite(startedMs)) {
      return Math.max(0, occurredMs - startedMs);
    }
  }

  const endMs = nextStep ? Date.parse(nextStep.occurredAt) : NaN;
  if (Number.isFinite(endMs)) {
    return Math.max(0, endMs - occurredMs);
  }
  return null;
}
