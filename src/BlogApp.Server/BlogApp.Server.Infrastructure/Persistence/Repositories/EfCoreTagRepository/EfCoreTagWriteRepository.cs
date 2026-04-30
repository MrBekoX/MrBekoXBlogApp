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
            INSERT INTO "tags" ("Id", "Name", "Slug", "CreatedAt", "IsDeleted")
            VALUES ({id}, {name}, {slug}, {now}, false)
            ON CONFLICT ("Name") WHERE "IsDeleted" = false DO NOTHING
            """,
            cancellationToken);

        // Must return a TRACKED entity: callers add this Tag to BlogPost.Tags before
        // SaveChanges. If we returned a detached entity, EF Core's graph traversal in
        // AddAsync(post) would mark the tag as Added and try to INSERT it again,
        // causing "duplicate key value violates unique constraint PK_tags" because
        // the raw SQL above is invisible to the ChangeTracker.
        return await _dbSet
            .FirstAsync(t => t.Name == name, cancellationToken);
    }
}
