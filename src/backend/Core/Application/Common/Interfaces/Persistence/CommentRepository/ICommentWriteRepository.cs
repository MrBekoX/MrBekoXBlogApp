using BlogApp.Core.Domain.Entities;

namespace BlogApp.Core.Application.Common.Interfaces.Persistence.CommentRepository;

public interface ICommentWriteRepository : IWriteRepository<Comment>
{
}
