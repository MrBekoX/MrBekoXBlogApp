using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Options;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.IdentityModel.Tokens;

namespace BlogApp.Presentation.Api.Extensions;

public static class AuthenticationExtensions
{
    public static IServiceCollection AddJwtAuthentication(this IServiceCollection services, IConfiguration configuration)
    {
        var jwtSettings = configuration.GetSection(JwtSettings.SectionName).Get<JwtSettings>()
            ?? throw new InvalidOperationException("JWT settings not configured");

        if (Encoding.UTF8.GetBytes(jwtSettings.Secret).Length < 32)
            throw new InvalidOperationException("JWT Secret must be at least 256 bits (32 bytes)");

        services.AddAuthentication(options =>
        {
            options.DefaultAuthenticateScheme = JwtBearerDefaults.AuthenticationScheme;
            options.DefaultChallengeScheme = JwtBearerDefaults.AuthenticationScheme;
        })
        .AddJwtBearer(JwtBearerDefaults.AuthenticationScheme, options =>
        {
            options.TokenValidationParameters = CreateAccessTokenValidationParameters(jwtSettings);
            options.Events = new JwtBearerEvents
            {
                OnMessageReceived = context =>
                {
                    if (string.IsNullOrEmpty(context.Token))
                    {
                        context.Token = context.Request.Cookies["accessToken"];
                    }
                    return Task.CompletedTask;
                },
                OnTokenValidated = async context =>
                {
                    var blacklist = context.HttpContext.RequestServices.GetService<ITokenBlacklistService>();
                    if (blacklist is null) return;

                    var jti = context.Principal?.FindFirstValue(JwtRegisteredClaimNames.Jti);
                    if (!string.IsNullOrEmpty(jti) && await blacklist.IsTokenBlacklistedAsync(jti))
                    {
                        context.Fail("Token has been revoked.");
                        return;
                    }

                    var userIdClaim = context.Principal?.FindFirstValue("UserId");
                    var iatClaim = context.Principal?.FindFirstValue(JwtRegisteredClaimNames.Iat);
                    if (!string.IsNullOrEmpty(userIdClaim) && Guid.TryParse(userIdClaim, out var userId)
                        && !string.IsNullOrEmpty(iatClaim) && long.TryParse(iatClaim, out var iatUnix))
                    {
                        var issuedAt = DateTimeOffset.FromUnixTimeSeconds(iatUnix).UtcDateTime;
                        if (await blacklist.AreUserTokensInvalidatedAsync(userId, issuedAt))
                        {
                            context.Fail("All user tokens have been invalidated.");
                            return;
                        }
                    }
                }
            };
        });

        services.AddAuthorization();

        return services;
    }

    private static TokenValidationParameters CreateAccessTokenValidationParameters(JwtSettings jwtSettings)
    {
        return new TokenValidationParameters
        {
            ValidateIssuerSigningKey = true,
            IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(jwtSettings.Secret)),
            ValidateIssuer = true,
            ValidIssuer = jwtSettings.Issuer,
            ValidateAudience = true,
            ValidAudience = jwtSettings.Audience,
            ValidateLifetime = true,
            ClockSkew = TimeSpan.FromSeconds(30),
            NameClaimType = ClaimTypes.NameIdentifier,
            RoleClaimType = ClaimTypes.Role
        };
    }
}
