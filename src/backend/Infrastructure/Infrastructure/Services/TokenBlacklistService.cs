using BlogApp.BuildingBlocks.Abstractions;
using BlogApp.Core.Application.Common.Interfaces.Services;

namespace BlogApp.Infrastructure.Services;

public class TokenBlacklistService(IBasicCacheService cache) : ITokenBlacklistService
{
    private const string BlacklistKeyPrefix = "jwt:blacklist:";
    private const string UserRevokedKeyPrefix = "jwt:user-revoked:";

    public async Task BlacklistTokenAsync(string jti, TimeSpan remainingLifetime, CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(jti) || remainingLifetime <= TimeSpan.Zero)
            return;

        var key = $"{BlacklistKeyPrefix}{jti}";
        await cache.SetAsync(key, true, remainingLifetime, ct);
    }

    public async Task InvalidateAllUserTokensAsync(Guid userId, CancellationToken ct = default)
    {
        var key = $"{UserRevokedKeyPrefix}{userId}";
        // Store current UTC timestamp — any token issued before this is invalid
        // TTL of 24 hours covers any possible token lifetime
        await cache.SetAsync(key, DateTime.UtcNow.Ticks, TimeSpan.FromHours(24), ct);
    }

    public async Task<bool> IsTokenBlacklistedAsync(string jti, CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(jti))
            return false;

        var key = $"{BlacklistKeyPrefix}{jti}";
        return await cache.ExistsAsync(key, ct);
    }

    public async Task<bool> AreUserTokensInvalidatedAsync(Guid userId, DateTime tokenIssuedAt, CancellationToken ct = default)
    {
        var key = $"{UserRevokedKeyPrefix}{userId}";
        var revokedTicks = await cache.GetAsync<long>(key, ct);

        if (revokedTicks == 0)
            return false;

        var revokedAt = new DateTime(revokedTicks, DateTimeKind.Utc);
        return tokenIssuedAt < revokedAt;
    }
}
