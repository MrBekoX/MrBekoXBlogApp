'use client';

/**
 * B10 yönetim gözlem sayfası (mrbekox-console/agent): plan admin listesinin
 * okuma görünümü — queue/job backlog + en eski iş yaşı, outbox yayın gecikmesi +
 * confirm hataları, duplicate/inbox + retry/DLQ sayıları, iş süreleri + lease
 * recovery + iptal gecikmesi, mod dağılımı ve geri bildirim özeti.
 * Veri kaynağı: GET /api/v1/agent/admin/observations (Admin rolüyle sınırlandırılmış;
 * backend tüm değerleri mevcut projection/outbox tablolarından okur).
 */

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { apiClient, getErrorMessage } from '@/lib/api';

interface AgentObservations {
  generatedAt: string;
  windowHours: number;
  acceptance: {
    activeRuns: number;
    oldestActiveRunAgeMinutes?: number | null;
    runsLastWindow: number;
  };
  outbox: {
    pending: number;
    claimed: number;
    published: number;
    deadLettered: number;
    oldestPendingAgeMinutes?: number | null;
    averagePublishLatencySeconds?: number | null;
    p95PublishLatencySeconds?: number | null;
    recordsWithPublishErrors: number;
    attemptSum: number;
  };
  projection: { applied: number; duplicates: number; stale: number; quarantined: number };
  runs: {
    averageRunSeconds?: number | null;
    maxRunSeconds?: number | null;
    averageCancelLatencySeconds?: number | null;
    modeCounts: Record<string, number>;
    terminalCounts: Record<string, number>;
    completedWithUnresolvedQuestions: number;
  };
  feedback: { total: number; averageRating?: number | null; ratingCounts: Record<string, number> };
  jobs?: {
    backlogByQueue: Record<string, number>;
    oldestBacklogAgeMinutes?: number | null;
    expiredLeaseRunning: number;
    statusCounts: Record<string, number>;
    jobsWithRetries: number;
  } | null;
}

const fmt = (value?: number | null, unit = '') =>
  value === null || value === undefined ? '—' : `${value.toFixed(value < 10 ? 1 : 0)}${unit}`;

async function readObservations() {
  return apiClient.get<{ success: boolean; data?: AgentObservations; errors?: string[] }>(
    '/agent/admin/observations', { params: { windowHours: 24 } },
  );
}

export default function AgentObservationsPage() {
  const [observations, setObservations] = useState<AgentObservations | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshedAt, setRefreshedAt] = useState<string | null>(null);

  const load = useCallback(() => readObservations()
    .then((response) => {
      setError(null);
      if (response.data.success && response.data.data) {
        setObservations(response.data.data);
        setRefreshedAt(new Date().toLocaleTimeString('tr-TR'));
      } else {
        setError(response.data.errors?.[0] ?? 'Gözlemler okunamadı');
      }
    }).catch((err) => {
      setError(getErrorMessage(err, 'Gözlemler okunamadı'));
    }).finally(() => {
      setIsLoading(false);
    }), []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Agent Gözlemleri</h1>
          <p className="text-sm text-muted-foreground">
            Outbox/projection ve iş kuyruğu gözlemleri (son {observations?.windowHours ?? 24} saat)
          </p>
        </div>
        <div className="flex items-center gap-3">
          {refreshedAt && <span className="text-xs text-muted-foreground">{refreshedAt}</span>}
          <Button variant="outline" size="sm" onClick={() => {
            setIsLoading(true);
            setError(null);
            void load();
          }} disabled={isLoading}>
            <RefreshCw className={`mr-1 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
            Yenile
          </Button>
        </div>
      </div>

      {error && <p className="text-sm text-red-500">{error}</p>}

      {isLoading && !observations ? (
        <div className="grid gap-4 md:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      ) : observations ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Kabul / İş Backlog&apos;u</CardTitle>
              <CardDescription>Çözümlenmemiş run sayısı ve en eski iş yaşı</CardDescription>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              <Row label="Aktif (Accepted) run" value={String(observations.acceptance.activeRuns)} />
              <Row
                label="En eski aktif iş yaşı"
                value={fmt(observations.acceptance.oldestActiveRunAgeMinutes, ' dk')}
              />
              <Row label="Penceredeki yeni run" value={String(observations.acceptance.runsLastWindow)} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Outbox Yayını</CardTitle>
              <CardDescription>Gecikme ve confirm/attempt hataları</CardDescription>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              <Row label="Pending / Claimed" value={`${observations.outbox.pending} / ${observations.outbox.claimed}`} />
              <Row label="Published / DLQ" value={`${observations.outbox.published} / ${observations.outbox.deadLettered}`} />
              <Row label="Ort. yayın gecikmesi" value={fmt(observations.outbox.averagePublishLatencySeconds, ' sn')} />
              <Row label="p95 yayın gecikmesi" value={fmt(observations.outbox.p95PublishLatencySeconds, ' sn')} />
              <Row label="Hatalı kayıt / deneme" value={`${observations.outbox.recordsWithPublishErrors} / ${observations.outbox.attemptSum}`} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Projection / Inbox</CardTitle>
              <CardDescription>Duplicate, stale ve karantina sayıları</CardDescription>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              <Row label="Uygulanan olay" value={String(observations.projection.applied)} />
              <Row label="Duplicate (yeniden uygulanmadı)" value={String(observations.projection.duplicates)} />
              <Row label="Stale (sıra gerilemesi)" value={String(observations.projection.stale)} />
              <Row label="Quarantined (bilinmeyen run)" value={String(observations.projection.quarantined)} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">İş Süreleri ve İptal</CardTitle>
              <CardDescription>Kabul→terminal ve iptal gecikmesi</CardDescription>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              <Row label="Ort. iş süresi" value={fmt(observations.runs.averageRunSeconds, ' sn')} />
              <Row label="En uzun iş" value={fmt(observations.runs.maxRunSeconds, ' sn')} />
              <Row label="Ort. iptal gecikmesi" value={fmt(observations.runs.averageCancelLatencySeconds, ' sn')} />
              <Row
                label="Mod dağılımı"
                value={Object.entries(observations.runs.modeCounts).map(([k, v]) => `${k}:${v}`).join(' ') || '—'}
              />
              <Row
                label="Terminal dağılımı"
                value={Object.entries(observations.runs.terminalCounts).map(([k, v]) => `${k}:${v}`).join(' ') || '—'}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Agent İş Kuyruğu</CardTitle>
              <CardDescription>agent şeması (Python); yoksa bölüm boş</CardDescription>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              {observations.jobs ? (
                <>
                  <Row
                    label="Bekleyen iş (queue)"
                    value={Object.entries(observations.jobs.backlogByQueue).map(([k, v]) => `${k}:${v}`).join(' ') || '0'}
                  />
                  <Row label="En eski bekleyen iş yaşı" value={fmt(observations.jobs.oldestBacklogAgeMinutes, ' dk')} />
                  <Row label="Lease'i bitmiş running (recovery adayı)" value={String(observations.jobs.expiredLeaseRunning)} />
                  <Row label="Retry'lı bekleyen iş" value={String(observations.jobs.jobsWithRetries)} />
                </>
              ) : (
                <p className="text-xs text-muted-foreground">agent şeması bu ortamda yok (B4 migration bekleniyor)</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Geri Bildirim</CardTitle>
              <CardDescription>Run sahipliğiyle kaydedilen kullanıcı puanları</CardDescription>
            </CardHeader>
            <CardContent className="space-y-1 text-sm">
              <Row label="Toplam kayıt" value={String(observations.feedback.total)} />
              <Row label="Ortalama puan" value={fmt(observations.feedback.averageRating, ' / 5')} />
              <Row
                label="Dağılım"
                value={
                  Object.entries(observations.feedback.ratingCounts)
                    .sort(([a], [b]) => Number(a) - Number(b))
                    .map(([k, v]) => `${k}★:${v}`)
                    .join(' ') || '—'
                }
              />
            </CardContent>
          </Card>
        </div>
      ) : null}

      <p className="text-xs text-muted-foreground">
        Bu sayfa yalnız okur; yeni ağır altyapı kurulmadan mevcut projection/outbox
        tablolarından üretilir. Kalite sinyali: yanıtlanmamış soru bırakan tamamlanan
        sonuçlar = {observations?.runs.completedWithUnresolvedQuestions ?? '—'}.
      </p>

      <div className="text-xs">
        <Link href="/mrbekox-console/dashboard" className="text-muted-foreground hover:text-foreground">
          ← Kontrol paneli
        </Link>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}
