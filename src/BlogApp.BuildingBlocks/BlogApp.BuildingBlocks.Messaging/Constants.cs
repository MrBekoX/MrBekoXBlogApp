namespace BlogApp.BuildingBlocks.Messaging;

/// <summary>
/// RabbitMQ topology constants.
/// These values define the messaging infrastructure shared between
/// .NET Publisher and Python Consumer.
/// </summary>
public static class MessagingConstants
{
    /// <summary>
    /// Main event exchange name (Direct type)
    /// </summary>
    public const string ExchangeName = "blog.events";

    /// <summary>
    /// AI analysis queue name (Quorum type) - AI Agent consumes
    /// </summary>
    public const string QueueName = "q.ai.analysis";

    /// <summary>
    /// Dead letter exchange for failed messages
    /// </summary>
    public const string DeadLetterExchange = "dlx.blog";

    /// <summary>
    /// Dead letter queue for failed messages
    /// </summary>
    public const string DeadLetterQueue = "dlq.ai.analysis";

    /// <summary>
    /// Routing keys for different event types
    /// </summary>
    public static class RoutingKeys
    {
        // Article events (Backend -> AI Agent)
        public const string ArticleCreated = "article.created";
        public const string ArticlePublished = "article.published";
        public const string ArticleUpdated = "article.updated";

        // AI Analysis events
        /// <summary>
        /// Backend requests AI analysis (Backend -> AI Agent)
        /// </summary>
        public const string AiAnalysisRequested = "ai.analysis.requested";

        /// <summary>
        /// AI Agent completes analysis (AI Agent -> Backend)
        /// </summary>
        public const string AiAnalysisCompleted = "ai.analysis.completed";

        // AI Generation request (Backend -> AI Agent)
        public const string AiTitleGenerationRequested = "ai.title.generation.requested";
        public const string AiExcerptGenerationRequested = "ai.excerpt.generation.requested";
        public const string AiTagsGenerationRequested = "ai.tags.generation.requested";
        public const string AiSeoGenerationRequested = "ai.seo.generation.requested";
        public const string AiContentImprovementRequested = "ai.content.improvement.requested";

        // AI Generation completed (AI Agent -> Backend)
        public const string AiTitleGenerationCompleted = "ai.title.generation.completed";
        public const string AiExcerptGenerationCompleted = "ai.excerpt.generation.completed";
        public const string AiTagsGenerationCompleted = "ai.tags.generation.completed";
        public const string AiSeoGenerationCompleted = "ai.seo.generation.completed";
        public const string AiContentImprovementCompleted = "ai.content.improvement.completed";

        // New AI Analysis request events (Backend -> AI Agent)
        public const string AiSummarizeRequested = "ai.summarize.requested";
        public const string AiKeywordsRequested = "ai.keywords.requested";
        public const string AiSentimentRequested = "ai.sentiment.requested";
        public const string AiReadingTimeRequested = "ai.reading-time.requested";
        public const string AiGeoOptimizeRequested = "ai.geo-optimize.requested";
        public const string AiCollectSourcesRequested = "ai.collect-sources.requested";

        // New AI Analysis completed events (AI Agent -> Backend)
        public const string AiSummarizeCompleted = "ai.summarize.completed";
        public const string AiKeywordsCompleted = "ai.keywords.completed";
        public const string AiSentimentCompleted = "ai.sentiment.completed";
        public const string AiReadingTimeCompleted = "ai.reading-time.completed";
        public const string AiGeoOptimizeCompleted = "ai.geo-optimize.completed";
        public const string AiCollectSourcesCompleted = "ai.collect-sources.completed";

        // Chat events
        /// <summary>
        /// Backend requests chat response (Backend -> AI Agent)
        /// </summary>
        public const string ChatMessageRequested = "chat.message.requested";

        /// <summary>
        /// AI Agent completes chat response (AI Agent -> Backend)
        /// </summary>
        public const string ChatMessageCompleted = "chat.message.completed";

        /// <summary>
        /// AI Agent streams chat chunk (AI Agent -> Backend) for chunked streaming
        /// </summary>
        public const string ChatChunkCompleted = "chat.chunk.completed";

        // Admin events (Backend -> AI Agent)
        public const string AdminQuarantineStatsRequested = "admin.quarantine.stats.requested";
        public const string AdminQueueStatsRequested = "admin.queue.stats.requested";
        public const string AdminQuarantineReplayRequested = "admin.quarantine.replay.requested";

        // Admin events completed (AI Agent -> Backend)
        public const string AdminQuarantineStatsCompleted = "admin.quarantine.stats.completed";
        public const string AdminQueueStatsCompleted = "admin.queue.stats.completed";
        public const string AdminQuarantineReplayCompleted = "admin.quarantine.replay.completed";
    }

    /// <summary>
    /// Queue names for different consumers
    /// </summary>
    public static class QueueNames
    {
        /// <summary>
        /// AI Agent consumes article events and analysis requests
        /// </summary>
        public const string AiAnalysis = "q.ai.analysis";

        /// <summary>
        /// Backend consumes AI analysis completed events
        /// </summary>
        public const string AiAnalysisCompleted = "q.ai.analysis.completed";

        /// <summary>
        /// AI Agent consumes chat message requests
        /// </summary>
        public const string ChatRequests = "q.chat.requests";

        /// <summary>
        /// Backend consumes chat response events
        /// </summary>
        public const string ChatResponses = "q.chat.responses";

        /// <summary>
        /// Backend consumes AI generation completed events (RPC responses)
        /// </summary>
        public const string AiGenerationCompleted = "q.ai.generation.completed";

        /// <summary>
        /// AI Agent consumes admin operations requests
        /// </summary>
        public const string AiAdmin = "q.ai.admin";

        /// <summary>
        /// Backend consumes admin operation completed events
        /// </summary>
        public const string AiAdminCompleted = "q.ai.admin.completed";

        /// <summary>
        /// AI Agent consumes authoring generation requests (medium priority)
        /// </summary>
        public const string AiAuthoring = "q.ai.authoring";

        /// <summary>
        /// AI Agent consumes background analysis requests (low priority)
        /// </summary>
        public const string AiBackground = "q.ai.background";
    }
}
