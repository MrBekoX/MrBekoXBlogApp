using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Interfaces.Persistence.UserRepository;

public interface IUserWriteRepository : IWriteRepository<User>
{
    Task UpdateLastLoginAsync(Guid userId, CancellationToken cancellationToken = default);
    Task IncrementFailedLoginAttemptsAsync(Guid userId, CancellationToken cancellationToken = default);
    Task ResetFailedLoginAttemptsAsync(Guid userId, CancellationToken cancellationToken = default);
}
