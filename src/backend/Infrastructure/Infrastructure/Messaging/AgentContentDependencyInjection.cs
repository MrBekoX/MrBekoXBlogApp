using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Core.Application.Common.Options;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace BlogApp.Infrastructure.Messaging;

/// <summary>
/// Registers durable content events, startup snapshot synchronization, and
/// presentation guards. AddAgentOutbox must provide the scoped outbox writer.
/// The startup service blocks HTTP readiness only when explicitly enabled.
/// </summary>
public static class AgentContentDependencyInjection
{
    public static IServiceCollection AddAgentContentEvents(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddOptions<AgentContentSyncSettings>()
            .Bind(configuration.GetSection(AgentContentSyncSettings.SectionName))
            .Validate(settings => settings.BatchSize is >= 1 and <= 1000, "AgentContentSync:BatchSize must be from 1 to 1000.")
            .Validate(settings => settings.StartupMaxAttempts is >= 1 and <= 10, "AgentContentSync:StartupMaxAttempts must be from 1 to 10.")
            .Validate(settings => settings.StartupRetryDelaySeconds is >= 0 and <= 60, "AgentContentSync:StartupRetryDelaySeconds must be from 0 to 60.")
            .ValidateOnStart();

        services.AddScoped<IAgentContentEventService, AgentContentEventService>();
        services.AddScoped<ContentSnapshotSyncService>();
        services.AddHostedService<ContentSyncStartupService>();
        services.AddScoped<IAgentResultPresentationGuard, AgentResultPresentationGuard>();

        return services;
    }
}
