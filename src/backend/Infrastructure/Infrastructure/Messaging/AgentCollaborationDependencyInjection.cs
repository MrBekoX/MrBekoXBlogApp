using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Collaboration;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace BlogApp.Infrastructure.Messaging;

/// <summary>
/// B9 iş birliği hat kayıtları (ADDITIVE): store + servis + politika ayarları.
/// B10 controller'ları AgentCollaborationService'i DI ile tüketir; projection
/// işleyicisi IAgentCollaborationStore'u aynı transaction'a katmak için alır.
/// ÖN KOŞUL: AddInfrastructure DbContext kaydı (store AppDbContext üstünde çalışır).
/// </summary>
public static class AgentCollaborationDependencyInjection
{
    public static IServiceCollection AddAgentCollaboration(
        this IServiceCollection services, IConfiguration configuration)
    {
        services.Configure<AgentCollaborationSettings>(
            configuration.GetSection(AgentCollaborationSettings.SectionName));
        services.AddScoped<IAgentCollaborationStore, EfAgentCollaborationStore>();
        services.AddScoped<AgentCollaborationService>();
        return services;
    }
}
