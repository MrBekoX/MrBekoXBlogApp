using BlogApp.Server.Application.Common.Interfaces.Persistence.CategoryRepository;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Infrastructure.Persistence;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreCategoryRepository;

public class EfCoreCategoryWriteRepository : EfCoreWriteRepository<Category>, ICategoryWriteRepository
{
    public EfCoreCategoryWriteRepository(AppDbContext context) : base(context)
    {
    }
}
