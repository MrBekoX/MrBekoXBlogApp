using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Interfaces.Persistence.CategoryRepository;

public interface ICategoryReadRepository : IReadRepository<Category>
{
    Task<Category?> GetBySlugAsync(string slug, CancellationToken cancellationToken = default);
    Task<IEnumerable<Category>> GetActiveCategoriesAsync(CancellationToken cancellationToken = default);
    Task<bool> IsSlugUniqueAsync(string slug, Guid? excludeId = null, CancellationToken cancellationToken = default);
}
