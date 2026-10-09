using BlogApp.Core.Domain.Entities;

namespace BlogApp.Core.Application.Common.Interfaces.Persistence.CategoryRepository;

public interface ICategoryReadRepository : IReadRepository<Category>
{
    Task<Category?> GetBySlugAsync(string slug, CancellationToken cancellationToken = default);
    Task<IEnumerable<Category>> GetActiveCategoriesAsync(CancellationToken cancellationToken = default);
    Task<bool> IsSlugUniqueAsync(string slug, Guid? excludeId = null, CancellationToken cancellationToken = default);
}
