using BlogApp.Server.Application.Common.Interfaces.Persistence.CommentRepository;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Infrastructure.Persistence;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreCommentRepository;

public class EfCoreCommentWriteRepository : EfCoreWriteRepository<Comment>, ICommentWriteRepository
{
    public EfCoreCommentWriteRepository(AppDbContext context) : base(context)
    {
    }
}
