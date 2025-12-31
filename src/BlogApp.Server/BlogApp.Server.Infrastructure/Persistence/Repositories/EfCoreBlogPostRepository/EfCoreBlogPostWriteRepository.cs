using BlogApp.Server.Application.Common.Interfaces.Persistence.BlogPostRepository;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Infrastructure.Persistence;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreBlogPostRepository;

public class EfCoreBlogPostWriteRepository : EfCoreWriteRepository<BlogPost>, IBlogPostWriteRepository
{
    public EfCoreBlogPostWriteRepository(AppDbContext context) : base(context)
    {
    }

    public async Task IncrementViewCountAsync(Guid postId, CancellationToken cancellationToken = default)
    {
        var post = await _dbSet.FindAsync([postId], cancellationToken);
        if (post != null)
        {
            post.ViewCount++;
        }
    }

    public async Task IncrementLikeCountAsync(Guid postId, CancellationToken cancellationToken = default)
    {
        var post = await _dbSet.FindAsync([postId], cancellationToken);
        if (post != null)
        {
            post.LikeCount++;
        }
    }
}
