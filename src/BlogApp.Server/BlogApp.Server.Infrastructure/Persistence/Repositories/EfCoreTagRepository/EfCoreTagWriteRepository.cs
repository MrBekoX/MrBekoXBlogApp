using BlogApp.Server.Application.Common.Interfaces.Persistence.TagRepository;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Infrastructure.Persistence;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreTagRepository;

public class EfCoreTagWriteRepository : EfCoreWriteRepository<Tag>, ITagWriteRepository
{
    public EfCoreTagWriteRepository(AppDbContext context) : base(context)
    {
    }
}
