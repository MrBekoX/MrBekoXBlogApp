using BlogApp.Core.Domain.Entities;

namespace BlogApp.Core.Application.Common.Interfaces.Persistence.CommentRepository;

public interface ICommentReadRepository : IReadRepository<Comment>
{
    Task<IEnumerable<Comment>> GetByPostIdAsync(Guid postId, CancellationToken cancellationToken = default);
    Task<IEnumerable<Comment>> GetByUserIdAsync(Guid userId, CancellationToken cancellationToken = default);
    Task<int> GetCommentCountByPostIdAsync(Guid postId, CancellationToken cancellationToken = default);
}
