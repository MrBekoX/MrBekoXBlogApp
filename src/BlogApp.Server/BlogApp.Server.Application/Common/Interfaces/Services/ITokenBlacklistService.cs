namespace BlogApp.Server.Application.Common.Interfaces.Services;

public interface ITokenBlacklistService
{
    Task BlacklistTokenAsync(string jti, TimeSpan remainingLifetime, CancellationToken ct = default);
    Task InvalidateAllUserTokensAsync(Guid userId, CancellationToken ct = default);
    Task<bool> IsTokenBlacklistedAsync(string jti, CancellationToken ct = default);
    Task<bool> AreUserTokensInvalidatedAsync(Guid userId, DateTime tokenIssuedAt, CancellationToken ct = default);
}
