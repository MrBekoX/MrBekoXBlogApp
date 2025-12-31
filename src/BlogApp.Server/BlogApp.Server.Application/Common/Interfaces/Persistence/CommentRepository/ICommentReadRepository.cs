using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Interfaces.Persistence.CommentRepository;

public interface ICommentReadRepository : IReadRepository<Comment>
{
    Task<IEnumerable<Comment>> GetByPostIdAsync(Guid postId, CancellationToken cancellationToken = default);
    Task<IEnumerable<Comment>> GetByUserIdAsync(Guid userId, CancellationToken cancellationToken = default);
    Task<int> GetCommentCountByPostIdAsync(Guid postId, CancellationToken cancellationToken = default);
}
