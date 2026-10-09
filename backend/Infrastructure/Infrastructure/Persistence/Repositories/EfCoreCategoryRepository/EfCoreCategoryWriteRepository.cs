using BlogApp.Core.Application.Common.Interfaces.Persistence.CategoryRepository;
using BlogApp.Core.Domain.Entities;
using BlogApp.Infrastructure.Persistence;

namespace BlogApp.Infrastructure.Persistence.Repositories.EfCoreCategoryRepository;

public class EfCoreCategoryWriteRepository : EfCoreWriteRepository<Category>, ICategoryWriteRepository
{
    public EfCoreCategoryWriteRepository(AppDbContext context) : base(context)
    {
    }
}
