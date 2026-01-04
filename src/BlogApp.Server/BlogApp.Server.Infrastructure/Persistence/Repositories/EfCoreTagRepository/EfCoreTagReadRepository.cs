using BlogApp.Server.Application.Common.Interfaces.Persistence.TagRepository;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreTagRepository;

public class EfCoreTagReadRepository : EfCoreReadRepository<Tag>, ITagReadRepository
{
    public EfCoreTagReadRepository(AppDbContext context) : base(context)
    {
    }

    public async Task<Tag?> GetBySlugAsync(string slug, CancellationToken cancellationToken = default)
    {
        return await _dbSet.AsNoTracking().FirstOrDefaultAsync(t => t.Slug == slug, cancellationToken);
    }

    public async Task<IEnumerable<Tag>> GetByNamesAsync(IEnumerable<string> names, CancellationToken cancellationToken = default)
    {
        // PostgreSQL is case-sensitive, so we need to compare in lowercase
        // Note: We intentionally do NOT use AsNoTracking() here because these tags 
        // will be added to Post.Tags collection. EF Core needs to track them to 
        // recognize them as existing entities, otherwise it will try to INSERT them again.
        var lowerNames = names.Select(n => n.ToLower()).ToList();
        return await _dbSet
            .Where(t => lowerNames.Contains(t.Name.ToLower()))
            .ToListAsync(cancellationToken);
    }

    public async Task<bool> IsSlugUniqueAsync(string slug, Guid? excludeId = null, CancellationToken cancellationToken = default)
    {
        var query = _dbSet.Where(t => t.Slug == slug);
        if (excludeId.HasValue)
            query = query.Where(t => t.Id != excludeId.Value);
        
        return !await query.AnyAsync(cancellationToken);
    }
}
