using System.Globalization;
using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Security;

namespace BlogApp.Presentation.Api.Security;

/// <summary>Shared current revocation checks for authenticated HTTP and hub calls.</summary>
public static class AccessTokenRevocationPolicy
{
    public static async Task<bool> IsRevokedAsync(ClaimsPrincipal principal,
        ITokenBlacklistService blacklist, CancellationToken cancellationToken = default)
    {
        var jti = principal.FindFirstValue(JwtRegisteredClaimNames.Jti);
        if (!string.IsNullOrEmpty(jti) && await blacklist.IsTokenBlacklistedAsync(jti, cancellationToken))
            return true;

        var identity = principal.FindFirstValue("userId") ?? principal.FindFirstValue("UserId")
            ?? principal.FindFirstValue(ClaimTypes.NameIdentifier) ?? principal.FindFirstValue(JwtRegisteredClaimNames.Sub);
        if (!Guid.TryParse(identity, out var userId)) return true;

        // Legacy tokens without issuance metadata stay usable until an account
        // cutoff exists. An unknown issuance time must never bypass that cutoff.
        var issuedAt = DateTime.MinValue;
        var standard = principal.FindFirstValue(JwtRegisteredClaimNames.Iat);
        var precise = principal.FindFirstValue(AccessTokenClaimTypes.IssuedAtTicks);
        if (precise is not null)
        {
            if (!long.TryParse(precise, NumberStyles.None, CultureInfo.InvariantCulture, out var ticks)
                || ticks > DateTime.MaxValue.Ticks
                || !TryUnixTime(standard, out var seconds)) return true;
            issuedAt = new DateTime(ticks, DateTimeKind.Utc);
            if (new DateTimeOffset(issuedAt).ToUnixTimeSeconds() != seconds) return true;
        }
        else if (standard is not null)
        {
            if (!TryUnixTime(standard, out var seconds)) return true;
            issuedAt = DateTimeOffset.FromUnixTimeSeconds(seconds).UtcDateTime;
        }
        return await blacklist.AreUserTokensInvalidatedAsync(userId, issuedAt, cancellationToken);
    }

    // JWT middleware checks lifetime on each HTTP request. Hub calls reuse a
    // cached principal, so they must check its expiration again explicitly.
    public static bool IsExpired(ClaimsPrincipal principal, TimeProvider? clock = null) =>
        !TryUnixTime(principal.FindFirstValue(JwtRegisteredClaimNames.Exp), out var expires)
        || expires <= (clock ?? TimeProvider.System).GetUtcNow().ToUnixTimeSeconds();

    private static bool TryUnixTime(string? value, out long seconds) =>
        long.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out seconds)
        && seconds <= DateTimeOffset.MaxValue.ToUnixTimeSeconds();
}
