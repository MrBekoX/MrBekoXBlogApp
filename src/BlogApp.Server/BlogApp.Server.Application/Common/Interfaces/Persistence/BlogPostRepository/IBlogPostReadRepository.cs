using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Interfaces.Persistence.BlogPostRepository;

/// <summary>
/// BlogPost entity için read repository arayüzü
/// </summary>
public interface IBlogPostReadRepository : IReadRepository<BlogPost>
{
    Task<IEnumerable<BlogPost>> GetPublishedPostsAsync(CancellationToken cancellationToken = default);
    Task<IEnumerable<BlogPost>> GetFeaturedPostsAsync(int count, CancellationToken cancellationToken = default);
    Task<IEnumerable<BlogPost>> GetPostsByCategoryAsync(Guid categoryId, CancellationToken cancellationToken = default);
    Task<IEnumerable<BlogPost>> GetPostsByTagAsync(Guid tagId, CancellationToken cancellationToken = default);
    Task<BlogPost?> GetBySlugAsync(string slug, CancellationToken cancellationToken = default);
}
