using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Interfaces.Persistence.RefreshTokenRepository;

public interface IRefreshTokenReadRepository : IReadRepository<RefreshToken>
{
    Task<RefreshToken?> GetByTokenAsync(string token, CancellationToken cancellationToken = default);
    Task<IEnumerable<RefreshToken>> GetActiveTokensByUserIdAsync(Guid userId, CancellationToken cancellationToken = default);
}
