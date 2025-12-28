using BlogApp.Server.Domain.Common;

namespace BlogApp.Server.Application.Common.Interfaces;

/// <summary>
/// Generic Write Repository arayüzü
/// </summary>
public interface IWriteRepository<T> : IRepository<T> where T : BaseEntity
{
    Task AddAsync(T entity, CancellationToken cancellationToken = default);
    Task AddRangeAsync(IEnumerable<T> entities, CancellationToken cancellationToken = default);
    Task RemoveAsync(T entity, CancellationToken cancellationToken = default);
    Task<bool> RemoveIdAsync(Guid id, CancellationToken cancellationToken = default);
    Task RemoveRangeAsync(IEnumerable<T> entities, CancellationToken cancellationToken = default);
    Task UpdateAsync(T entity, CancellationToken cancellationToken = default);
    Task UpdateRangeAsync(IEnumerable<T> entities, CancellationToken cancellationToken = default);
}