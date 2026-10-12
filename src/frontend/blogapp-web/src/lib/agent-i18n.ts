/**
 * Agent paneli iki dilli metinleri (B10: "Türkçe/İngilizce metinler").
 * Mevcut site tek dillidir (lang="tr"); global i18n çerçevesi kurulmadan
 * panel KAPSAMINDA basit sözlük yaklaşımı kullanılır — mevcut sayfalar
 * etkilenmez. Dil, tarayıcı dilinden tek seferlik çözülür; varsayılan tr.
 */

export type AgentLang = 'tr' | 'en';

export function detectAgentLang(): AgentLang {
  if (typeof navigator === 'undefined') return 'tr';
  return navigator.language?.toLowerCase().startsWith('en') ? 'en' : 'tr';
}

const tr = {
  panelTitle: 'Bu yazıya sorun',
  panelDescription: 'Makale bağlamında soru cevap, özet ve derin araştırma.',
  questionLabel: 'Sorunuz',
  questionPlaceholder: 'Bu yazıdaki ana fikir nedir? Belirli bir kod bloğunu açıkla...',
  includeArticleContext: 'Makale bağlamını açıkça dahil et',
  modeLabel: 'Çalışma tercihi',
  modeAuto: 'Auto (sistem seçsin)',
  modeFast: 'Hızlı yanıt',
  modeAnalysis: 'Analiz',
  modeDeepResearch: 'Derin araştırma',
  send: 'Soru sor',
  sendResearch: 'Derin araştırma başlat',
  sending: 'Gönderiliyor...',
  // Ayrık durumlar: kabul → başlama → tamamlanma (plan B10)
  statusSubmitting: 'İsteğiniz gönderiliyor...',
  statusAccepted: 'İş kabul edildi; kuyruğa alındı.',
  statusStarting: 'Agent işi alıyor, başlıyor...',
  statusStarted: 'Çalışıyor',
  statusCompleted: 'Tamamlandı',
  statusPartial: 'Kısmen tamamlandı',
  statusFailed: 'Tamamlanamadı',
  statusCancelled: 'İptal edildi',
  statusCancelling: 'İptal isteniyor...', // cancel intent kabul edildi; terminal değil
  liveUpdatesOff: 'Canlı bildirim kapalı; sayfa yenileme ile güncellenir.',
  liveUpdatesOn: 'Canlı güncelleme açık.',
  cancel: 'İptal et',
  cancelConfirm: 'Bu çalışma iptal edilsin mi?',
  retry: 'Yeniden sor',
  sources: 'Kaynaklar',
  sourceArticle: 'Makale bölümü',
  sourceWeb: 'Web kaynağı',
  sectionLink: 'İlgili bölüme git',
  feedbackQuestion: 'Bu yanıt yardımcı oldu mu?',
  feedbackThanks: 'Geri bildiriminiz kaydedildi.',
  feedbackRecorded: 'Kaydedildi',
  resumeHint: 'Devam etmek için sürüm doğrulanıyor...',
  runNotFound: 'Bu iş için kayıtlı çalışma bulunamadı.',
  runForbidden: 'Bu iş size ait değil.',
  errorGeneric: 'İş başlatılamadı. Lütfen tekrar deneyin.',
  askedQuestion: 'Sorulan soru',
  duration: 'Süre',
  selectedMode: 'Seçilen mod',
  answerHeading: 'Yanıt',
  reportHeading: 'Rapor',
  unresolved: 'Yanıtlanamayan sorular kaldı',
  contentUnavailable: 'İçerik kullanılamıyor',
  language: 'Dil',
  a11yStatusPrefix: 'Durum bildirimi',
} as const;

/** Genişletilmiş metin tipi: alan adları tr sözlüğünden, değer tipleri string. */
export type AgentTexts = { [K in keyof typeof tr]: string };

const en: AgentTexts = {
  panelTitle: 'Ask about this article',
  panelDescription: 'Question answering in article context, summaries and deep research.',
  questionLabel: 'Your question',
  questionPlaceholder: 'What is the main idea? Explain a specific code block...',
  includeArticleContext: 'Explicitly include article context',
  modeLabel: 'Execution preference',
  modeAuto: 'Auto (system decides)',
  modeFast: 'Fast answer',
  modeAnalysis: 'Analysis',
  modeDeepResearch: 'Deep research',
  send: 'Ask',
  sendResearch: 'Start deep research',
  sending: 'Sending...',
  statusSubmitting: 'Submitting your request...',
  statusAccepted: 'Run accepted; queued.',
  statusStarting: 'Agent is picking up the job, starting...',
  statusStarted: 'Running',
  statusCompleted: 'Completed',
  statusPartial: 'Partially completed',
  statusFailed: 'Failed',
  statusCancelled: 'Cancelled',
  statusCancelling: 'Cancellation requested...',
  liveUpdatesOff: 'Live updates off; refresh to see progress.',
  liveUpdatesOn: 'Live updates on.',
  cancel: 'Cancel',
  cancelConfirm: 'Cancel this run?',
  retry: 'Ask again',
  sources: 'Sources',
  sourceArticle: 'Article section',
  sourceWeb: 'Web source',
  sectionLink: 'Go to section',
  feedbackQuestion: 'Was this answer helpful?',
  feedbackThanks: 'Your feedback was recorded.',
  feedbackRecorded: 'Recorded',
  resumeHint: 'Validating version to resume...',
  runNotFound: 'No run found for this job.',
  runForbidden: 'This run belongs to another session.',
  errorGeneric: 'Could not start the run. Please try again.',
  askedQuestion: 'Question',
  duration: 'Duration',
  selectedMode: 'Selected mode',
  answerHeading: 'Answer',
  reportHeading: 'Report',
  unresolved: 'Some questions remain unresolved',
  contentUnavailable: 'Content unavailable',
  language: 'Language',
  a11yStatusPrefix: 'Status announcement',
};

export const agentTexts: Record<AgentLang, AgentTexts> = { tr, en };
