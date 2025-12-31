using BlogApp.Server.Application.Common.Interfaces.Persistence.UserRepository;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Infrastructure.Persistence;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreUserRepository;

public class EfCoreUserWriteRepository : EfCoreWriteRepository<User>, IUserWriteRepository
{
    public EfCoreUserWriteRepository(AppDbContext context) : base(context)
    {
    }

    public async Task UpdateLastLoginAsync(Guid userId, CancellationToken cancellationToken = default)
    {
        var user = await _dbSet.FindAsync([userId], cancellationToken);
        if (user != null)
        {
            user.LastLoginAt = DateTime.UtcNow;
        }
    }

    public async Task IncrementFailedLoginAttemptsAsync(Guid userId, CancellationToken cancellationToken = default)
    {
        var user = await _dbSet.FindAsync([userId], cancellationToken);
        if (user != null)
        {
            user.FailedLoginAttempts++;
        }
    }

    public async Task ResetFailedLoginAttemptsAsync(Guid userId, CancellationToken cancellationToken = default)
    {
        var user = await _dbSet.FindAsync([userId], cancellationToken);
        if (user != null)
        {
            user.FailedLoginAttempts = 0;
            user.LockoutEndTime = null;
        }
    }
}
