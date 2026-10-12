using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Core.Application.Common.Options;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace BlogApp.Infrastructure.Messaging;

/// <summary>
/// B8 içerik olay hattı kayıtları (ADDITIVE): makale değişim olaylarını outbox'a yazan
/// servis, backend'in başlattığı ilk içerik senkronizasyonu ve makale kaynaklı sonucun
/// sunum öncesi güncellik denetimi. ÖN KOŞUL: <see cref="AgentOutboxDependencyInjection.AddAgentOutbox"/>
/// (B3) — outbox yazıcısı ve relay kayıtlı olmalıdır.
/// Program.cs bağlaması B10'un kompozisyon adımıdır (B3/B5 deseni: servis + extension
/// bu fazda hazır, host kaydı kompozisyon fazında).
/// </summary>
public static class AgentContentDependencyInjection
{
    public static IServiceCollection AddAgentContentEvents(this IServiceCollection services, IConfiguration configuration)
    {
        services.Configure<AgentContentSyncSettings>(configuration.GetSection(AgentContentSyncSettings.SectionName));

        services.AddScoped<IAgentContentEventService, AgentContentEventService>();
        services.AddScoped<ContentSnapshotSyncService>();
        services.AddScoped<IAgentResultPresentationGuard, AgentResultPresentationGuard>();

        return services;
    }
}
