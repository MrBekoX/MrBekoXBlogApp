using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;

namespace BlogApp.BuildingBlocks.Messaging;

/// <summary>B2 broker istemcilerinin DI kaydı. Publisher/consumer örnekleri uygulama katmanında
/// (B3 outbox publisher, B4 event consumer) rol bazlı exchange kümesiyle kaydedilir.</summary>
public static class RabbitMqMessagingDependencyInjection
{
    public static IServiceCollection AddRabbitMqAgentMessaging(this IServiceCollection services, IConfiguration configuration)
    {
        services.Configure<RabbitMqSettings>(configuration.GetSection(RabbitMqSettings.SectionName));
        services.AddSingleton<RabbitMqSettings>(sp => sp.GetRequiredService<IOptions<RabbitMqSettings>>().Value);
        services.AddSingleton<IRabbitMqConnectionManager, RabbitMqConnectionManager>();
        services.AddSingleton<AgentTopologyInitializer>();
        return services;
    }
}
