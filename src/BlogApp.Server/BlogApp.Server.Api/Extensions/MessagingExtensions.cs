using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Server.Api.Hubs;
using BlogApp.Server.Api.Messaging;
using BlogApp.Server.Api.Services;
using BlogApp.Server.Application.Common.Events;
using BlogApp.Server.Application.Common.Interfaces.Services;

namespace BlogApp.Server.Api.Extensions;

public static class MessagingExtensions
{
    public static IServiceCollection AddMessagingAndSignalR(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddMessagingServices(configuration);

        // SignalR for real-time cache invalidation notifications
        services.AddSignalR();
        services.AddScoped<ICacheInvalidationNotifier, CacheInvalidationNotifier>();

        // Register RabbitMQ event consumers for AI analysis
        services.AddEventConsumer<AiAnalysisCompletedEvent, AiAnalysisCompletedHandler>(
            queueName: MessagingConstants.QueueNames.AiAnalysisCompleted,
            routingKey: MessagingConstants.RoutingKeys.AiAnalysisCompleted);

        // Register RabbitMQ event consumers for chat responses
        services.AddEventConsumer<ChatResponseEvent, ChatResponseHandler>(
            queueName: MessagingConstants.QueueNames.ChatResponses,
            routingKey: MessagingConstants.RoutingKeys.ChatMessageCompleted);

        services.AddEventConsumerHostedService();

        return services;
    }
}
