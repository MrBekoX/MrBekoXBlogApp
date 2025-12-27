using BlogApp.Server.Domain.Common;

namespace BlogApp.Server.Application.Common.Interfaces;

/// <summary>
/// Generic Write Repository arayüzü
/// </summary>
public interface IWriteRepository<T> where T : BaseEntity
{
    Task<T> AddAsync(T entity, CancellationToken cancellationToken = default);
    Task AddRangeAsync(IEnumerable<T> entities, CancellationToken cancellationToken = default);
    void Update(T entity);
    void UpdateRange(IEnumerable<T> entities);
    void Delete(T entity);
    void DeleteRange(IEnumerable<T> entities);
}