using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Interfaces.Persistence.RefreshTokenRepository;

public interface IRefreshTokenWriteRepository : IWriteRepository<RefreshToken>
{
    Task RevokeAllUserTokensAsync(Guid userId, CancellationToken cancellationToken = default);
    Task CleanupExpiredTokensAsync(CancellationToken cancellationToken = default);
}
