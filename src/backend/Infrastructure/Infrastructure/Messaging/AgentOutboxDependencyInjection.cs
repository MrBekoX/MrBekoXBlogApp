using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace BlogApp.Infrastructure.Messaging;

/// <summary>
/// B3 agent backend mesajlaşma kayıtları: kabul komutunun outbox yazıcısı ve outbox relay
/// hosted service. ÖN KOŞUL: <see cref="RabbitMqMessagingDependencyInjection.AddRabbitMqAgentMessaging"/>
/// (B2) kayıtlı olmalıdır — relay, connection manager + RabbitMqSettings'i DI'dan alır.
/// B10 tarafından Program.cs'te çağrılır:
///   builder.Services.AddRabbitMqAgentMessaging(configuration);
///   builder.Services.AddAgentOutbox(configuration);
/// (K3: AgentTopologyInitializer açılışta InitializeAsync ile çağrılmalıdır; passive declare
/// başarısız olursa relay kayıtları beklemede tutar ve tekrar dener.)
/// </summary>
public static class AgentOutboxDependencyInjection
{
    public static IServiceCollection AddAgentOutbox(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddOptions<AgentAcceptanceSettings>()
            .Bind(configuration.GetSection(AgentAcceptanceSettings.SectionName))
            .Validate(s => s.MaxActiveRunsPerOwner > 0 && s.MaxActiveRunsTotal > 0,
                "Agent acceptance quotas must be positive.")
            .Validate(s => s.DeadlineReaperIntervalSeconds is >= 1 and <= 300,
                "AgentAcceptance:DeadlineReaperIntervalSeconds must be from 1 to 300.")
            .Validate(s => s.TerminalRecoveryGraceSeconds is >= 0 and <= 1800,
                "AgentAcceptance:TerminalRecoveryGraceSeconds must be from 0 to 1800.")
            .ValidateOnStart();
        services.Configure<AgentOutboxRelaySettings>(configuration.GetSection(AgentOutboxRelaySettings.SectionName));

        services.AddScoped<IOutboxWriter, EfOutboxWriter>();

        // Backend yayını rolü: komut + içerik exchange'leri (K3 yetki kapsamı; events yayınlanmaz).
        // Somut tip kaydedilir çünkü IAgentBrokerPublisher (B2, donuk) StartAsync'i içermiyor;
        // yaşam döngüsü yöntemi somut sınıftadır (B2 raporlanacak küçük arayüz eksisi).
        services.AddSingleton<RabbitMqAgentPublisher>(sp => new RabbitMqAgentPublisher(
            sp.GetRequiredService<IRabbitMqConnectionManager>(),
            sp.GetRequiredService<RabbitMqSettings>(),
            [AgentMessagingTopology.CommandsExchange, AgentMessagingTopology.ContentExchange]));
        services.AddSingleton<IAgentBrokerPublisher>(sp => sp.GetRequiredService<RabbitMqAgentPublisher>());

        services.AddHostedService<OutboxRelayService>();
        services.AddScoped<AgentRunDeadlineReaper>();
        services.AddHostedService<AgentRunDeadlineService>();

        return services;
    }
}

/// <summary>Outbox kaydını ortam transaction'ının içinde AppDbContext.OutboxMessages setine ekler.</summary>
public sealed class EfOutboxWriter(AppDbContext context) : IOutboxWriter
{
    public async Task AddAsync(Core.Domain.Entities.OutboxMessage message, CancellationToken cancellationToken = default)
    {
        await context.OutboxMessages.AddAsync(message, cancellationToken);
    }
}
