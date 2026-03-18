using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Interfaces.Persistence.RefreshTokenRepository;

public interface IRefreshTokenWriteRepository : IWriteRepository<RefreshToken>
{
    Task RevokeAllUserTokensAsync(Guid userId, CancellationToken cancellationToken = default);
    Task CleanupExpiredTokensAsync(CancellationToken cancellationToken = default);

    /// <summary>
    /// Atomically revokes a refresh token only when it has not already been revoked
    /// (WHERE RevokedAt IS NULL). Returns <c>true</c> when exactly one row was updated;
    /// <c>false</c> when the token was already consumed by a concurrent request,
    /// indicating a token-reuse attack or a harmless retry.
    /// </summary>
    Task<bool> TryRevokeAsync(string token, string? ipAddress, string reason, CancellationToken cancellationToken = default);
}
