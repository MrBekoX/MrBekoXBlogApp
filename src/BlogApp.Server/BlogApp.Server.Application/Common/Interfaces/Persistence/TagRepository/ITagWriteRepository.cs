using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Interfaces.Persistence.TagRepository;

public interface ITagWriteRepository : IWriteRepository<Tag>
{
    /// <summary>
    /// Atomically inserts a tag if one with the same name does not exist,
    /// then returns the persisted tag. Uses INSERT ... ON CONFLICT DO NOTHING
    /// to eliminate the read-then-write race condition.
    /// </summary>
    Task<Tag> GetOrCreateAsync(string name, string slug, CancellationToken cancellationToken = default);
}
