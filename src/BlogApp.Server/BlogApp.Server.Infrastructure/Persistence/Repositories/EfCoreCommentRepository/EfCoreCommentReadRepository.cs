using BlogApp.Server.Application.Common.Interfaces.Persistence.CommentRepository;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreCommentRepository;

public class EfCoreCommentReadRepository : EfCoreReadRepository<Comment>, ICommentReadRepository
{
    public EfCoreCommentReadRepository(AppDbContext context) : base(context)
    {
    }

    public async Task<IEnumerable<Comment>> GetByPostIdAsync(Guid postId, CancellationToken cancellationToken = default)
    {
        return await _dbSet
            .AsNoTracking()
            .Include(c => c.User)
            .Where(c => c.PostId == postId)
            .OrderByDescending(c => c.CreatedAt)
            .ToListAsync(cancellationToken);
    }

    public async Task<IEnumerable<Comment>> GetByUserIdAsync(Guid userId, CancellationToken cancellationToken = default)
    {
        return await _dbSet
            .AsNoTracking()
            .Include(c => c.Post)
            .Where(c => c.UserId == userId)
            .OrderByDescending(c => c.CreatedAt)
            .ToListAsync(cancellationToken);
    }

    public async Task<int> GetCommentCountByPostIdAsync(Guid postId, CancellationToken cancellationToken = default)
    {
        return await _dbSet.CountAsync(c => c.PostId == postId, cancellationToken);
    }
}
