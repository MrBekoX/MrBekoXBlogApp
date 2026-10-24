using BlogApp.Presentation.Api.Security;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.Extensions.Options;

namespace BlogApp.Presentation.Api.Extensions;

public static class TrustedProxyExtensions
{
    public static IServiceCollection AddTrustedProxyForwarding(this IServiceCollection services, IConfiguration configuration)
    {
        services.AddOptions<ApiTrustedProxySettings>()
            .Bind(configuration.GetSection(ApiTrustedProxySettings.SectionName))
            .Validate(value => !value.Enabled || TrustedForwardedHeadersConfiguration.HasValidExactPeers(value),
                "Enabled forwarding requires exact trusted proxy IPs; an empty list, wildcard or network is invalid.")
            .ValidateOnStart();
        services.AddSingleton<IPostConfigureOptions<ForwardedHeadersOptions>, TrustedForwardedHeadersConfiguration>();
        return services;
    }
}
