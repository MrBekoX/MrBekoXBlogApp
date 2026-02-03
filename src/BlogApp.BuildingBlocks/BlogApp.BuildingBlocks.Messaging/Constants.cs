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

        // Chat events
        /// <summary>
        /// Backend requests chat response (Backend -> AI Agent)
        /// </summary>
        public const string ChatMessageRequested = "chat.message.requested";

        /// <summary>
        /// AI Agent completes chat response (AI Agent -> Backend)
        /// </summary>
        public const string ChatMessageCompleted = "chat.message.completed";
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
    }
}
