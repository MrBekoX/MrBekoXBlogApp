using BlogApp.Server.Application.Common.Interfaces.Persistence.TagRepository;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreTagRepository;

public class EfCoreTagWriteRepository : EfCoreWriteRepository<Tag>, ITagWriteRepository
{
    public EfCoreTagWriteRepository(AppDbContext context) : base(context)
    {
    }

    /// <inheritdoc />
    public async Task<Tag> GetOrCreateAsync(string name, string slug, CancellationToken cancellationToken = default)
    {
        var id = Guid.NewGuid();
        var now = DateTime.UtcNow;

        // Single atomic statement: insert only if no row with this name exists.
        // ON CONFLICT DO NOTHING prevents the race condition without needing
        // application-level locking or retry loops.
        await _context.Database.ExecuteSqlAsync(
            $"""
            INSERT INTO "Tags" ("Id", "Name", "Slug", "CreatedAt")
            VALUES ({id}, {name}, {slug}, {now})
            ON CONFLICT ("Name") DO NOTHING
            """,
            cancellationToken);

        return await _dbSet
            .AsNoTracking()
            .FirstAsync(t => t.Name == name, cancellationToken);
    }
}
