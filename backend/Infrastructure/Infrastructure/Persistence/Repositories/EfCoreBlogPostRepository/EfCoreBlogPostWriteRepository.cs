using BlogApp.Core.Application.Common.Interfaces.Persistence.BlogPostRepository;
using BlogApp.Core.Domain.Entities;
using BlogApp.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Infrastructure.Persistence.Repositories.EfCoreBlogPostRepository;

public class EfCoreBlogPostWriteRepository : EfCoreWriteRepository<BlogPost>, IBlogPostWriteRepository
{
    public EfCoreBlogPostWriteRepository(AppDbContext context) : base(context)
    {
    }

    /// <summary>
    /// Atomik olarak ViewCount'u artırır (race condition önlemi)
    /// </summary>
    public async Task IncrementViewCountAsync(Guid postId, CancellationToken cancellationToken = default)
    {
        await _dbSet
            .Where(p => p.Id == postId)
            .ExecuteUpdateAsync(
                setters => setters.SetProperty(p => p.ViewCount, p => p.ViewCount + 1),
                cancellationToken);
    }

    /// <summary>
    /// Atomik olarak LikeCount'u artırır (race condition önlemi)
    /// </summary>
    public async Task IncrementLikeCountAsync(Guid postId, CancellationToken cancellationToken = default)
    {
        await _dbSet
            .Where(p => p.Id == postId)
            .ExecuteUpdateAsync(
                setters => setters.SetProperty(p => p.LikeCount, p => p.LikeCount + 1),
                cancellationToken);
    }
}
