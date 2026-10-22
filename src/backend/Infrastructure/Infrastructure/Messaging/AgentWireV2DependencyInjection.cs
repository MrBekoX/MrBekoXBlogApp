using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace BlogApp.Infrastructure.Messaging;

/// <summary>
/// Who am I / wire v2 kayıtları (K2, K4, K6): üretici anahtarı (<see cref="AgentWireV2Settings"/>),
/// broker hazırlık bariyeri, run sürüm seçici ve v2 konuşma geçmişi derleyicisi.
/// ÖN KOŞUL: <c>AddRabbitMqAgentMessaging</c> (bağlantı yöneticisi) ve <c>AddInfrastructureServices</c>
/// (canonical profil kaynağı <see cref="Core.Application.Common.AuthorProfile.IAuthorProfileSource"/>).
/// </summary>
public static class AgentWireV2DependencyInjection
{
    public static IServiceCollection AddAgentWireV2(this IServiceCollection services, IConfiguration configuration)
    {
        services.Configure<AgentWireV2Settings>(configuration.GetSection(AgentWireV2Settings.SectionName));

        services.AddSingleton<IAgentWireV2Readiness, RabbitMqAgentWireV2Readiness>();
        services.AddScoped<IAgentWireVersionSelector, AgentWireVersionSelector>();
        services.AddScoped<IAgentConversationHistoryComposer, AgentConversationHistoryComposer>();

        return services;
    }
}
