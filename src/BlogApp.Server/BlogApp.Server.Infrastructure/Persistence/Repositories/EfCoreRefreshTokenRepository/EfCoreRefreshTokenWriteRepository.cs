using BlogApp.Server.Application.Common.Interfaces.Persistence.RefreshTokenRepository;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreRefreshTokenRepository;

public class EfCoreRefreshTokenWriteRepository : EfCoreWriteRepository<RefreshToken>, IRefreshTokenWriteRepository
{
    public EfCoreRefreshTokenWriteRepository(AppDbContext context) : base(context)
    {
    }

    /// <inheritdoc />
    public async Task<bool> TryRevokeAsync(string token, string? ipAddress, string reason, CancellationToken cancellationToken = default)
    {
        var now = DateTime.UtcNow;
        var affected = await _dbSet
            .Where(rt => rt.Token == token && rt.RevokedAt == null)
            .ExecuteUpdateAsync(
                s => s
                    .SetProperty(rt => rt.RevokedAt, now)
                    .SetProperty(rt => rt.RevokedByIp, ipAddress)
                    .SetProperty(rt => rt.ReasonRevoked, reason),
                cancellationToken)
            .ConfigureAwait(false);

        return affected == 1;
    }

    public async Task RevokeAllUserTokensAsync(Guid userId, CancellationToken cancellationToken = default)
    {
        var tokens = await _dbSet
            .Where(rt => rt.UserId == userId && rt.RevokedAt == null)
            .ToListAsync(cancellationToken);

        foreach (var token in tokens)
        {
            token.RevokedAt = DateTime.UtcNow;
        }
    }

    public async Task CleanupExpiredTokensAsync(CancellationToken cancellationToken = default)
    {
        var expiredTokens = await _dbSet
            .Where(rt => rt.ExpiresAt < DateTime.UtcNow)
            .ToListAsync(cancellationToken);

        _dbSet.RemoveRange(expiredTokens);
    }
}
