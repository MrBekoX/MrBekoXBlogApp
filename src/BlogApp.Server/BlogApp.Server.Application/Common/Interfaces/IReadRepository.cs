using System.Linq.Expressions;
using BlogApp.Server.Domain.Common;

namespace BlogApp.Server.Application.Common.Interfaces;

/// <summary>
/// Generic Read Repository arayüzü
/// </summary>
public interface IReadRepository<T> where T : BaseEntity
{
    Task<T?> GetByIdAsync(Guid id, CancellationToken cancellationToken = default);
    Task<T?> GetAsync(Expression<Func<T, bool>> predicate, CancellationToken cancellationToken = default);
    Task<List<T>> GetAllAsync(CancellationToken cancellationToken = default);
    Task<List<T>> GetListAsync(Expression<Func<T, bool>> predicate, CancellationToken cancellationToken = default);
    Task<bool> AnyAsync(Expression<Func<T, bool>> predicate, CancellationToken cancellationToken = default);
    Task<int> CountAsync(Expression<Func<T, bool>>? predicate = null, CancellationToken cancellationToken = default);
    IQueryable<T> Query();
}