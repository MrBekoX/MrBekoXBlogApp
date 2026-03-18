using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Server.Api.Hubs;
using BlogApp.Server.Api.Messaging;
using BlogApp.Server.Api.Middlewares;
using BlogApp.Server.Api.Services;
using BlogApp.Server.Application.Common.Events;
using BlogApp.Server.Application.Common.Interfaces.Services;
using Microsoft.Extensions.Configuration;

namespace BlogApp.Server.Api.Extensions;

public static class MessagingExtensions
{
    public static IServiceCollection AddMessagingAndSignalR(this IServiceCollection services, IConfiguration configuration)
    {
        // Configure SignalR rate limiting options
        services.Configure<SignalRRateLimitOptions>(
            configuration.GetSection(SignalRRateLimitOptions.SectionName));

        services.AddMessagingServices(configuration);

        // SignalR for real-time cache invalidation notifications
        // Configure keep-alive and timeouts to prevent frequent disconnections
        services.AddSignalR(options =>
        {
            // Send keep-alive ping every 10 seconds (default is 15s)
            options.KeepAliveInterval = TimeSpan.FromSeconds(10);
            // Client timeout - server considers client disconnected after 30s of no activity
            options.ClientTimeoutInterval = TimeSpan.FromSeconds(30);
            // Maximum amount of time to wait for a handshake response
            options.HandshakeTimeout = TimeSpan.FromSeconds(15);
            // Enable detailed errors in development
            options.EnableDetailedErrors = configuration["Environment"] == "Development";
        });
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

        // AI Generation RPC response consumer (correlation-based)
        services.AddHostedService<AiGenerationResponseConsumer>();

        return services;
    }
}
