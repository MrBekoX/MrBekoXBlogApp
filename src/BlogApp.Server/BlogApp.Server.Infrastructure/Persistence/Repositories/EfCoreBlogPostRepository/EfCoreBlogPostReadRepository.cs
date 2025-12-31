using BlogApp.Server.Application.Common.Interfaces.Persistence.BlogPostRepository;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.Enums;
using BlogApp.Server.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreBlogPostRepository;

public class EfCoreBlogPostReadRepository : EfCoreReadRepository<BlogPost>, IBlogPostReadRepository
{
    public EfCoreBlogPostReadRepository(AppDbContext context) : base(context)
    {
    }

    public async Task<IEnumerable<BlogPost>> GetPublishedPostsAsync(CancellationToken cancellationToken = default)
    {
        return await _dbSet
            .AsNoTracking()
            .Where(p => p.Status == PostStatus.Published && p.PublishedAt <= DateTime.UtcNow)
            .OrderByDescending(p => p.PublishedAt)
            .ToListAsync(cancellationToken);
    }

    public async Task<IEnumerable<BlogPost>> GetFeaturedPostsAsync(int count, CancellationToken cancellationToken = default)
    {
        return await _dbSet
            .AsNoTracking()
            .Where(p => p.Status == PostStatus.Published && p.IsFeatured)
            .OrderByDescending(p => p.PublishedAt)
            .Take(count)
            .ToListAsync(cancellationToken);
    }

    public async Task<IEnumerable<BlogPost>> GetPostsByCategoryAsync(Guid categoryId, CancellationToken cancellationToken = default)
    {
        return await _dbSet
            .AsNoTracking()
            .Where(p => p.CategoryId == categoryId && p.Status == PostStatus.Published)
            .OrderByDescending(p => p.PublishedAt)
            .ToListAsync(cancellationToken);
    }

    public async Task<IEnumerable<BlogPost>> GetPostsByTagAsync(Guid tagId, CancellationToken cancellationToken = default)
    {
        return await _dbSet
            .AsNoTracking()
            .Where(p => p.Tags.Any(t => t.Id == tagId) && p.Status == PostStatus.Published)
            .OrderByDescending(p => p.PublishedAt)
            .ToListAsync(cancellationToken);
    }

    public async Task<BlogPost?> GetBySlugAsync(string slug, CancellationToken cancellationToken = default)
    {
        return await _dbSet
            .AsNoTracking()
            .Include(p => p.Author)
            .Include(p => p.Category)
            .Include(p => p.Tags)
            .FirstOrDefaultAsync(p => p.Slug == slug, cancellationToken);
    }
}
