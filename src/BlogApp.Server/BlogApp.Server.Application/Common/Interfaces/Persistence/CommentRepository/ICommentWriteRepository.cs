using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Interfaces.Persistence.CommentRepository;

public interface ICommentWriteRepository : IWriteRepository<Comment>
{
}
