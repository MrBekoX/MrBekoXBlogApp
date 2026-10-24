import { AUTHOR_NAME } from './site-config';

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

/** SSR/hydration için sabit sunucu dili: sunucu HTML'i her zaman 'tr' üretir;
 * tarayıcı dili hydration SONRASI uygulanır (useAgentLang). */
export const AGENT_SERVER_LANG: AgentLang = 'tr';

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
  statusReconciling: 'Sonuç kesinleştiriliyor',
  finalVerificationUnavailable: 'Bağlantı sorunu nedeniyle son durum doğrulanamadı. Sonucu tekrar kontrol edin veya sayfayı yenileyin; çalışma yeniden gönderilmedi.',
  checkFinalResult: 'Son durumu kontrol et',
  provisionalTerminalHint: 'Çalışma süre sınırına ulaştı. Sonucun kesinleşmesi kısa bir süre daha kontrol ediliyor; yeni bir istek göndermeden önce bekleyin.',
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
  // Who am I konusu (K7): konu seçici, çalışma tercihinden AYRI kavramdır
  topicLabel: 'Konu',
  topicAuto: 'Otomatik',
  topicWhoAmI: `Who am I · ${AUTHOR_NAME}`,
  topicHint: 'Konu değişince yeni bir sohbet başlar.',
  topicLockedHint: 'Çalışma sürerken konu değiştirilemez.',
  topicChanged: 'Konu değişti; yeni sohbet başladı.',
  whoAmITitle: `Who am I · ${AUTHOR_NAME}`,
  whoAmIAskTitle: `${AUTHOR_NAME} hakkında sorun`,
  whoAmIPanelDescription:
    `${AUTHOR_NAME} hakkında yayımlanmış profil bilgilerine dayanarak cevap verir; kaynaklar profil bölümlerine bağlanır.`,
  whoAmIInputPlaceholder: `${AUTHOR_NAME} hakkında sorun... (Enter gönderir)`,
  whoAmIScopeNote: 'Yalnız yayımlanmış profil kullanılır; makale bağlamı ve web araştırması bu konuda kapalıdır.',
  whoAmISuggestionWho: `${AUTHOR_NAME} kimdir?`,
  whoAmISuggestionEducation: 'Hangi üniversitede okudu?',
  whoAmISuggestionTeaching: 'Eğitmenlik deneyimi var mı?',
  whoAmISuggestionArchitecture: 'Mimari yaklaşımı nedir?',
  whoAmIStatusStarted: 'Profil bölümleri inceleniyor',
  whoAmIVerifiedAnswerNote: 'Yanıt, kaynak denetiminden sonra tek seferde gösterilir.',
  whoAmIUnavailable: 'Who am I şu an kullanılamıyor. Lütfen daha sonra tekrar deneyin.',
  researchNotAllowed: 'Bu konuda derin araştırma kullanılamaz.',
  sourceProfile: 'Profil',
  sourceProfileSection: 'Profil bölümü',
  sourceUnlinked: 'Bağlantı doğrulanamadı',
  unavailableProfileUpdated:
    'Profil bilgisi bu yanıttan sonra güncellendi; eski yanıt gösterilmiyor. Güncel bilgi için soruyu yeniden sorun.',
  unavailableProfileUnavailable:
    'Profil bilgisi şu an kullanılamıyor; bu yanıt gösterilemiyor. Daha sonra yeniden sorabilirsiniz.',
  unavailableLegacyProfile:
    'Bu eski profil yanıtı artık doğrulanamıyor. Güncel bilgi için soruyu yeniden sorun.',
  askAgain: 'Soruyu yeniden sor',
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
  statusReconciling: 'Confirming the final result',
  finalVerificationUnavailable: 'A connection problem prevented confirmation of the final status. Check again or reload; the run was not resubmitted.',
  checkFinalResult: 'Check final status',
  provisionalTerminalHint: 'The run reached its time limit. We are checking briefly for its final result; wait before sending another request.',
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
  suggestionCode: 'Explain the code sample',
  newContent: 'New content',
  cancelRequestedNote: 'Your cancellation request was sent; you will be notified when the run ends.',
  retryFailed: 'Resend the last question',
  a11yStepStarted: 'Step started',
  a11yNewSteps: 'New processing steps available',
  // Who am I topic (K7): the topic selector is SEPARATE from the execution preference
  topicLabel: 'Topic',
  topicAuto: 'Automatic',
  topicWhoAmI: `Who am I · ${AUTHOR_NAME}`,
  topicHint: 'Changing the topic starts a new conversation.',
  topicLockedHint: 'The topic cannot be changed while a run is active.',
  topicChanged: 'Topic changed; a new conversation started.',
  whoAmITitle: `Who am I · ${AUTHOR_NAME}`,
  whoAmIAskTitle: `Ask about ${AUTHOR_NAME}`,
  whoAmIPanelDescription:
    `Answers from ${AUTHOR_NAME}'s published profile; sources link to profile sections.`,
  whoAmIInputPlaceholder: `Ask about ${AUTHOR_NAME}... (Enter to send)`,
  whoAmIScopeNote: 'Only the published profile is used; article context and web research are off for this topic.',
  whoAmISuggestionWho: `Who is ${AUTHOR_NAME}?`,
  whoAmISuggestionEducation: 'Which university did they attend?',
  whoAmISuggestionTeaching: 'Do they have teaching experience?',
  whoAmISuggestionArchitecture: 'What is their architectural approach?',
  whoAmIStatusStarted: 'Reviewing profile sections',
  whoAmIVerifiedAnswerNote: 'The answer is shown at once after source validation.',
  whoAmIUnavailable: 'Who am I is currently unavailable. Please try again later.',
  researchNotAllowed: 'Deep research is not available for this topic.',
  sourceProfile: 'Profile',
  sourceProfileSection: 'Profile section',
  sourceUnlinked: 'Link could not be verified',
  unavailableProfileUpdated:
    'The profile was updated after this answer, so the old answer is hidden. Ask again for current information.',
  unavailableProfileUnavailable:
    'Profile information is currently unavailable, so this answer cannot be shown. You can ask again later.',
  unavailableLegacyProfile:
    'This older profile answer can no longer be verified. Ask again for current information.',
  askAgain: 'Ask the question again',
};

export const agentTexts: Record<AgentLang, AgentTexts> = { tr, en };

/** Konuya göre panel metinleri (başlık, açıklama, placeholder, durum, öneriler). */
export interface AgentTopicTexts {
  title: string;
  description: string;
  placeholder: string;
  statusStarted: string;
  suggestions: string[];
}

export function agentTopicTexts(lang: AgentLang, topic: 'auto' | 'who_am_i'): AgentTopicTexts {
  const t = agentTexts[lang];
  if (topic === 'who_am_i') {
    return {
      title: t.whoAmITitle,
      description: t.whoAmIPanelDescription,
      placeholder: t.whoAmIInputPlaceholder,
      statusStarted: t.whoAmIStatusStarted,
      suggestions: [
        t.whoAmISuggestionWho,
        t.whoAmISuggestionEducation,
        t.whoAmISuggestionTeaching,
        t.whoAmISuggestionArchitecture,
      ],
    };
  }
  return {
    title: t.panelTitle,
    description: t.panelDescription,
    placeholder: t.inputPlaceholder,
    statusStarted: t.statusStarted,
    suggestions: [t.suggestionSummary, t.suggestionMainIdea, t.suggestionCode],
  };
}

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
