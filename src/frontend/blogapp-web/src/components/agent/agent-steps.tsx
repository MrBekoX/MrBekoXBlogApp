'use client';

/**
 * Canlı işlem adımları paneli (daraltılabilir accordion).
 *
 * Dürüstlük kuralları: satırlar yalnız GERÇEK gelen olaylardan üretilir
 * (buildAgentSteps — bekleyen/sahte adım gösterilmez). "Çalışıyor" durumu
 * yalnız SON gelen progressed adımına verilir; süresi canlı elapsed'tir
 * (occurredAt'tan now'a — parent 1 sn'lik gerçek saat tiki verir). Nabız
 * animasyonu motion-safe ile sınırlıdır (prefers-reduced-motion'da düz).
 * Paralel worker olayları geldiği sırayla TEK listede akar.
 */

import { ChevronDown } from 'lucide-react';
import { agentStepKindLabels, agentTexts, type AgentLang } from '@/lib/agent-i18n';
import {
  formatDuration,
  isTerminalKind,
  isWaitingInputKind,
  settledStepDurationMs,
  summarizeDetail,
  type AgentStepKind,
  type AgentStepVM,
} from './agent-steps-model';

interface AgentStepsPanelProps {
  steps: AgentStepVM[];
  /** Çalışma sürüyor mu? (son progressed adımı "çalışıyor" gösterilir) */
  runActive: boolean;
  lang: AgentLang;
  open: boolean;
  onToggle: () => void;
  /** Canlı elapsed için güncel saat (parent ticker'ı; ms). */
  now: number;
}

export function AgentStepsPanel({ steps, runActive, lang, open, onToggle, now }: AgentStepsPanelProps) {
  if (steps.length === 0) return null;

  const t = agentTexts[lang];
  const kindLabels = agentStepKindLabels[lang];
  const last = steps[steps.length - 1];
  // needs_input (B9) terminal DEĞİLDİR ama çalışmıyor da: nabız yok, bekleme gösterilir.
  const lastIsRunning = runActive && !isTerminalKind(last.kind) && !isWaitingInputKind(last.kind);

  return (
    <div className="rounded border border-ide-border bg-black/20" data-testid="agent-steps">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls="agent-steps-list"
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs text-gray-300 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-ide-primary"
      >
        <span className="flex items-center gap-2">
          {lastIsRunning && (
            <span
              aria-hidden="true"
              className="h-1.5 w-1.5 rounded-full bg-ide-primary motion-safe:animate-pulse"
            />
          )}
          {t.stepsTitle}
          <span className="text-gray-600">({steps.length})</span>
        </span>
        <ChevronDown
          aria-hidden="true"
          className={`h-3.5 w-3.5 shrink-0 text-gray-500 transition-transform ${open ? '' : 'rotate-180'}`}
        />
      </button>

      {open && (
        <ol id="agent-steps-list" className="space-y-1 border-t border-ide-border px-3 py-2">
          {steps.map((step, index) => {
            const isRunning = index === steps.length - 1 && lastIsRunning;
            const label = kindLabels[step.kind] ?? step.kind;
            const duration = stepDurationText(step, steps[index + 1], isRunning, now, lang);
            const summary = step.message ?? '';
            const detailLines = isRunning ? [] : summarizeDetail(step.detail);
            // Yerleşmiş adımın dürüst durumu: başarıdan AYRI başarısızlık/iptal/
            // kısmi/bekleme görselleştirmesi (nokta rengi + ekran okuyucu eki).
            const settled = isRunning ? null : settledStepStatus(step.kind, t);

            return (
              <li
                key={step.sequence}
                className={`flex flex-col gap-0.5 rounded px-2 py-1.5 ${
                  isRunning ? 'bg-ide-primary/5 ring-1 ring-ide-primary/30' : ''
                }`}
              >
                <div className="flex items-start gap-2">
                  <span
                    aria-hidden="true"
                    className={`mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full ${
                      isRunning ? 'bg-ide-primary motion-safe:animate-pulse' : settled!.dot
                    }`}
                  />
                  <span
                    className={`flex-1 text-xs ${isRunning ? 'font-medium text-ide-primary' : settled!.tone}`}
                  >
                    {label}
                    <span className="sr-only">
                      {isRunning ? ` — ${t.stepRunning}` : ` — ${settled!.sr}`}
                    </span>
                  </span>
                  {duration && (
                    <span
                      className="shrink-0 font-mono text-[10px] text-gray-500"
                      title={t.duration}
                    >
                      {duration}
                    </span>
                  )}
                </div>
                {summary && summary !== label && (
                  <p className="pl-3.5 text-[11px] leading-snug text-gray-500">{summary}</p>
                )}
                {detailLines.length > 0 && (
                  <ul className="pl-3.5">
                    {detailLines.map((entry) => (
                      <li key={entry.key} className="text-[11px] leading-snug text-gray-500">
                        <span className="text-gray-400">{entry.key}:</span> {entry.value}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

/** Yerleşmiş adımın durum görünümü: nokta rengi, etiket tonu ve ekran okuyucu
 * eki kind'tan türetilir — başarısız/iptal/kısmi adımlar 'tamamlandı' YAZILMAZ
 * (yeşil nokta + "— tamamlandı" yalnız gerçek başarı ve nötr yerleşim içindir). */
function settledStepStatus(
  kind: AgentStepKind,
  t: (typeof agentTexts)['tr'],
): { dot: string; tone: string; sr: string } {
  switch (kind) {
    case 'failed':
      return { dot: 'bg-red-500', tone: 'text-red-400', sr: t.stepFailed };
    case 'cancelled':
      return { dot: 'bg-gray-500', tone: 'text-gray-400', sr: t.stepCancelled };
    case 'partial':
      return { dot: 'bg-amber-500', tone: 'text-amber-400', sr: t.stepPartial };
    case 'needs_input':
      return { dot: 'bg-amber-400', tone: 'text-amber-400', sr: t.stepNeedsInput };
    case 'tool_error':
      // Tekil araç hatası: adım başarısız ama çalışma kısmi yolda sürer —
      // run hatasının kırmızısı değil amber.
      return { dot: 'bg-amber-500', tone: 'text-amber-400', sr: t.stepToolError };
    default:
      return { dot: 'bg-emerald-500', tone: 'text-gray-300', sr: t.stepDone };
  }
}

/** Adım süresi metni: çalışan adım = canlı elapsed (occurredAt→now);
 * yerleşmiş adım = settledStepDurationMs (eşli fark ya da sonraki olaya kadar
 * gerçek pencere). Zaman damgalarının tamamı gerçek olaylardan gelir. */
function stepDurationText(
  step: AgentStepVM,
  nextStep: AgentStepVM | undefined,
  isRunning: boolean,
  now: number,
  lang: AgentLang,
): string | null {
  if (isRunning) {
    const occurredMs = Date.parse(step.occurredAt);
    if (!Number.isFinite(occurredMs)) return null;
    return formatDuration(Math.max(0, now - occurredMs), lang);
  }

  const settled = settledStepDurationMs(step, nextStep);
  return settled === null ? null : formatDuration(settled, lang);
}
