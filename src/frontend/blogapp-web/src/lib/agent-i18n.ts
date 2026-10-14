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
  // Sohbet arayüzü (canlı işlem adımları)
  chatLabel: 'Sohbet',
  youLabel: 'Sen',
  agentLabel: 'Agent',
  inputLabel: 'Mesajınız',
  inputPlaceholder: 'Sorunuzu yazın... (Enter gönderir)',
  sendHint: 'Enter gönderir · Shift+Enter yeni satır',
  stepsTitle: 'İşlem adımları',
  stepsHide: 'Adımları gizle',
  stepsShow: 'Adımları göster',
  stepRunning: 'çalışıyor',
  stepDone: 'tamamlandı',
  // Yerleşmiş adım durumları (ekran okuyucu eki): başarıdan AYRI dürüst durumlar
  stepFailed: 'başarısız',
  stepCancelled: 'iptal edildi',
  stepPartial: 'kısmen tamamlandı',
  stepNeedsInput: 'girdi bekleniyor',
  stepToolError: 'araç çağrısı başarısız',
  statusNeedsInput: 'Girdi bekleniyor', // B9: run terminal değil, ek girdi bekler
  statusGenerating: 'Yanıt yazılıyor...', // generation_delta canlı akışı göstergesi
  resumeAction: 'Devam et',
  suggestionsLabel: 'Örneğin:',
  suggestionSummary: 'Bu yazıyı kısaca özetle',
  suggestionMainIdea: 'Bu yazının ana fikri nedir?',
  suggestionCode: 'Kod örneğini açıkla',
  newContent: 'Yeni içerik',
  cancelRequestedNote: 'İptal talebiniz iletildi; çalışma sonlanınca bildirilecek.',
  retryFailed: 'Son soruyu tekrar gönder',
  a11yStepStarted: 'Adım başladı',
  a11yNewSteps: 'Yeni işlem adımları var',
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
  // Chat interface (live processing steps)
  chatLabel: 'Conversation',
  youLabel: 'You',
  agentLabel: 'Agent',
  inputLabel: 'Your message',
  inputPlaceholder: 'Type your question... (Enter to send)',
  sendHint: 'Enter to send · Shift+Enter for a new line',
  stepsTitle: 'Processing steps',
  stepsHide: 'Hide steps',
  stepsShow: 'Show steps',
  stepRunning: 'running',
  stepDone: 'done',
  // Settled step states (screen reader suffix): honest states distinct from success
  stepFailed: 'failed',
  stepCancelled: 'cancelled',
  stepPartial: 'partially completed',
  stepNeedsInput: 'waiting for input',
  stepToolError: 'tool call failed',
  statusNeedsInput: 'Waiting for input', // B9: run is not terminal, awaits extra input
  statusGenerating: 'Writing the answer...', // live generation_delta indicator
  resumeAction: 'Resume',
  suggestionsLabel: 'For example:',
  suggestionSummary: 'Summarize this article briefly',
  suggestionMainIdea: 'What is the main idea of this article?',
  suggestionCode: 'Explain the code example',
  newContent: 'New content',
  cancelRequestedNote: 'Your cancellation request was sent; you will be notified when the run ends.',
  retryFailed: 'Resend the last question',
  a11yStepStarted: 'Step started',
  a11yNewSteps: 'New processing steps available',
};

export const agentTexts: Record<AgentLang, AgentTexts> = { tr, en };

/**
 * Ortak olay sözleşmesi kind → kullanıcı-dostu adım etiketi (TR/EN).
 * kind değerleri: progressed payload'ından (progress_kind enum) veya terminal
 * messageType son ekinden türetilir (bkz. agent-steps-model.ts deriveEventKind).
 * 'progress': kind taşımayan progressed olayı için genel etiket (sözleşme
 * zenginleştirmesi gelmemiş kayıtlar; olay gerçektir, alt türü bilinmiyor).
 */
export const agentStepKindLabels: Record<AgentLang, Record<string, string>> = {
  tr: {
    run_started: 'Çalışma başlatıldı',
    mode_selected: 'Çalışma modu seçildi',
    article_context_ready: 'Makale bağlamı hazır',
    run_resumed: 'Kaldığı yerden devam ediyor',
    retrieval_started: 'İlgili belgeler inceleniyor',
    retrieval_completed: 'İlgili bölümler bulundu',
    research_started: 'Kaynaklar aranıyor',
    research_round_completed: 'Araştırma turu tamamlandı',
    generation_started: 'Cevap hazırlanıyor',
    generation_completed: 'Cevap üretildi',
    validation_completed: 'Kaynak ve kapsam kontrolü tamamlandı',
    action_proposed: 'İş birliği önerisi hazır',
    needs_input: 'Girdi bekleniyor',
    tool_error: 'Araç hatası',
    completed: 'Tamamlandı',
    failed: 'Başarısız',
    cancelled: 'İptal edildi',
    partial: 'Kısmi sonuç',
    progress: 'İlerleme güncellemesi',
  },
  en: {
    run_started: 'Run started',
    mode_selected: 'Execution mode selected',
    article_context_ready: 'Article context ready',
    run_resumed: 'Resuming from where it left off',
    retrieval_started: 'Reviewing relevant documents',
    retrieval_completed: 'Relevant sections found',
    research_started: 'Searching sources',
    research_round_completed: 'Research round completed',
    generation_started: 'Preparing the answer',
    generation_completed: 'Answer produced',
    validation_completed: 'Source and scope validation completed',
    action_proposed: 'Collaboration proposal ready',
    needs_input: 'Waiting for input',
    tool_error: 'Tool error',
    completed: 'Completed',
    failed: 'Failed',
    cancelled: 'Cancelled',
    partial: 'Partial result',
    progress: 'Progress update',
  },
};
