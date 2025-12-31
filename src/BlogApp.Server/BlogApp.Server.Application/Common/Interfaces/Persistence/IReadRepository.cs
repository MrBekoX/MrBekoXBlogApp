using System.Linq.Expressions;
using BlogApp.Server.Domain.Common;

namespace BlogApp.Server.Application.Common.Interfaces.Persistence;

/// <summary>
/// Generic Read Repository arayüzü
/// </summary>
public interface IReadRepository<T> where T : BaseEntity
{
    IQueryable<T> GetAll();
    IQueryable<T> GetWhere(Expression<Func<T, bool>> predicate);
    IQueryable<T> Query();
    Task<IEnumerable<T>> GetAllAsync(CancellationToken cancellationToken = default);
    Task<IEnumerable<T>> GetWhereAsync(Expression<Func<T, bool>> predicate, CancellationToken cancellationToken = default);
    Task<T?> GetByIdAsync(Guid id, CancellationToken cancellationToken = default);
    Task<T?> GetSingleAsync(Expression<Func<T, bool>> predicate, CancellationToken cancellationToken = default);
    Task<bool> ExistsAsync(Expression<Func<T, bool>> predicate, CancellationToken cancellationToken = default);
    Task<int> CountAsync(CancellationToken cancellationToken = default);
    Task<int> CountWhereAsync(Expression<Func<T, bool>> predicate, CancellationToken cancellationToken = default);
}
