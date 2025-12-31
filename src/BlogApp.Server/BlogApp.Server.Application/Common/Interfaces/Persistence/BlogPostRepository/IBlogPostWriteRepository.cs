using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Interfaces.Persistence.BlogPostRepository;

/// <summary>
/// BlogPost entity için write repository arayüzü
/// </summary>
public interface IBlogPostWriteRepository : IWriteRepository<BlogPost>
{
    Task IncrementViewCountAsync(Guid postId, CancellationToken cancellationToken = default);
    Task IncrementLikeCountAsync(Guid postId, CancellationToken cancellationToken = default);
}
