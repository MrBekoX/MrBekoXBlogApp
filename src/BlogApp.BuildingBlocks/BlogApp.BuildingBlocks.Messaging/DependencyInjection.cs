using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.BuildingBlocks.Messaging.Options;
using BlogApp.BuildingBlocks.Messaging.RabbitMQ;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace BlogApp.BuildingBlocks.Messaging;

/// <summary>
/// Dependency injection extensions for messaging services
/// </summary>
public static class DependencyInjection
{
    /// <summary>
    /// Add messaging services to the service collection
    /// </summary>
    /// <param name="services">Service collection</param>
    /// <param name="configuration">Application configuration</param>
    /// <returns>Service collection for chaining</returns>
    public static IServiceCollection AddMessagingServices(this IServiceCollection services, IConfiguration configuration)
    {
        // Configure RabbitMQ settings
        services.Configure<RabbitMqSettings>(configuration.GetSection(RabbitMqSettings.SectionName));

        var rabbitMqSettings = configuration.GetSection(RabbitMqSettings.SectionName).Get<RabbitMqSettings>();

        if (rabbitMqSettings?.Enabled == true)
        {
            // Register RabbitMQ connection as singleton (TCP connections are expensive)
            services.AddSingleton<RabbitMqConnection>();

            // Register event bus as scoped (one per request)
            services.AddScoped<IEventBus, RabbitMqEventBus>();
        }
        else
        {
            // Register no-op event bus when RabbitMQ is disabled
            services.AddScoped<IEventBus, NoOpEventBus>();
        }

        return services;
    }

    /// <summary>
    /// Add an event consumer for handling specific event types from RabbitMQ.
    /// Call this multiple times to register multiple event handlers.
    /// </summary>
    /// <typeparam name="TEvent">Event type implementing IIntegrationEvent</typeparam>
    /// <typeparam name="THandler">Handler type implementing IEventHandler&lt;TEvent&gt;</typeparam>
    /// <param name="services">Service collection</param>
    /// <param name="queueName">Queue name to consume from</param>
    /// <param name="routingKey">Routing key to bind the queue to</param>
    /// <returns>Service collection for chaining</returns>
    public static IServiceCollection AddEventConsumer<TEvent, THandler>(
        this IServiceCollection services,
        string queueName,
        string routingKey)
        where TEvent : IIntegrationEvent
        where THandler : class, IEventHandler<TEvent>
    {
        // Register the handler
        services.AddScoped<THandler>();
        services.AddScoped<IEventHandler<TEvent>>(sp => sp.GetRequiredService<THandler>());

        // Register consumer configuration
        services.AddSingleton(new EventConsumerConfig
        {
            QueueName = queueName,
            RoutingKey = routingKey,
            EventType = typeof(TEvent),
            HandlerType = typeof(THandler)
        });

        return services;
    }

    /// <summary>
    /// Add the RabbitMQ event consumer background service.
    /// Call this after registering all event consumers with AddEventConsumer.
    /// </summary>
    /// <param name="services">Service collection</param>
    /// <returns>Service collection for chaining</returns>
    public static IServiceCollection AddEventConsumerHostedService(this IServiceCollection services)
    {
        services.AddHostedService<RabbitMqEventConsumer>();
        return services;
    }
}
