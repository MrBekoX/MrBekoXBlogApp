using BlogApp.Core.Application.Common.Interfaces.Persistence.CommentRepository;
using BlogApp.Core.Domain.Entities;
using BlogApp.Infrastructure.Persistence;

namespace BlogApp.Infrastructure.Persistence.Repositories.EfCoreCommentRepository;

public class EfCoreCommentWriteRepository : EfCoreWriteRepository<Comment>, ICommentWriteRepository
{
    public EfCoreCommentWriteRepository(AppDbContext context) : base(context)
    {
    }
}
