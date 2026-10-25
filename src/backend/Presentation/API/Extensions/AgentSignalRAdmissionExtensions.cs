using BlogApp.Presentation.Api.Middlewares;
using BlogApp.Presentation.Api.Hubs;
using BlogApp.Presentation.Api.Security;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace BlogApp.Presentation.Api.Extensions;

public static class AgentSignalRAdmissionExtensions
{
    public static HubEndpointConventionBuilder MapAgentRunsHub(this IEndpointRouteBuilder endpoints) =>
        endpoints.MapHub<AgentRunsHub>(AgentRunsHub.HubPath,
            options => options.CloseOnAuthenticationExpiration = true).AllowAnonymous();

    public static IServiceCollection AddAgentSignalRAdmission(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddOptions<SignalRRateLimitOptions>().Bind(configuration.GetSection(SignalRRateLimitOptions.SectionName))
            .Validate(s => s.MaxConnectionsPerIp > 0 && s.MaxConnectionsTotal > 0
                           && s.MaxInvocationsPerMinute > 0 && s.MaxTrackedSubjects is >= 3 and <= 65536,
                "SignalR admission limits must be positive; MaxTrackedSubjects must be 3..65536.")
            .ValidateOnStart();
        services.TryAddSingleton<TimeProvider>(TimeProvider.System);
        services.AddSingleton<SignalRAdmissionControl>();
        services.AddSingleton<AgentHubInvocationRateLimitFilter>();
        services.AddSignalR(options => options.AddFilter<AgentHubInvocationRateLimitFilter>());
        return services;
    }
}
