using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.BuildingBlocks.Messaging.Options;
using BlogApp.BuildingBlocks.Messaging.RabbitMQ;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace BlogApp.BuildingBlocks.Messaging;

public static class DependencyInjection
{
    public static IServiceCollection AddMessagingServices(this IServiceCollection services, IConfiguration configuration)
    {
        services.Configure<RabbitMqSettings>(configuration.GetSection(RabbitMqSettings.SectionName));

        var rabbitMqSettings = configuration.GetSection(RabbitMqSettings.SectionName).Get<RabbitMqSettings>();

        if (rabbitMqSettings?.Enabled == true)
        {
            services.AddSingleton<RabbitMqConnection>();
            services.AddScoped<IEventBus, RabbitMqEventBus>();
        }
        else
        {
            services.AddScoped<IEventBus, NoOpEventBus>();
        }

        return services;
    }

    public static IServiceCollection AddEventConsumer<TEvent, THandler>(
        this IServiceCollection services,
        string queueName,
        string routingKey)
        where TEvent : IIntegrationEvent
        where THandler : class, IEventHandler<TEvent>
    {
        services.AddScoped<THandler>();
        services.AddScoped<IEventHandler<TEvent>>(sp => sp.GetRequiredService<THandler>());

        services.AddSingleton(new EventConsumerConfig
        {
            QueueName = queueName,
            RoutingKey = routingKey,
            EventType = typeof(TEvent),
            HandlerType = typeof(THandler)
        });

        return services;
    }

    public static IServiceCollection AddEventConsumerHostedService(this IServiceCollection services)
    {
        services.AddHostedService<RabbitMqEventConsumer>();
        return services;
    }
}
