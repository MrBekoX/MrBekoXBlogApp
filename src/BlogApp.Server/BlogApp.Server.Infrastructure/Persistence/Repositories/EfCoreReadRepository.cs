using System.Linq.Expressions;
using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Domain.Common;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories;

/// <summary>
/// Generic EF Core Read Repository implementasyonu
/// </summary>
public class EfCoreReadRepository<T> : EfCoreRepository<T>, IReadRepository<T> where T : BaseEntity
{
    public EfCoreReadRepository(AppDbContext context) : base(context)
    {
    }

    public IQueryable<T> GetAll()
    {
        return _dbSet.AsQueryable();
    }

    public IQueryable<T> GetWhere(Expression<Func<T, bool>> predicate)
    {
        return _dbSet.Where(predicate);
    }

    public IQueryable<T> Query()
    {
        return _dbSet.AsQueryable();
    }

    public async Task<IEnumerable<T>> GetAllAsync(CancellationToken cancellationToken = default)
    {
        return await _dbSet.ToListAsync(cancellationToken);
    }

    public async Task<IEnumerable<T>> GetWhereAsync(Expression<Func<T, bool>> predicate, CancellationToken cancellationToken = default)
    {
        return await _dbSet.Where(predicate).ToListAsync(cancellationToken);
    }

    public async Task<T?> GetByIdAsync(Guid id, CancellationToken cancellationToken = default)
    {
        return await _dbSet.FindAsync(new object[] { id }, cancellationToken);
    }

    public async Task<T?> GetSingleAsync(Expression<Func<T, bool>> predicate, CancellationToken cancellationToken = default)
    {
        return await _dbSet.FirstOrDefaultAsync(predicate, cancellationToken);
    }

    public async Task<bool> ExistsAsync(Expression<Func<T, bool>> predicate, CancellationToken cancellationToken = default)
    {
        return await _dbSet.AnyAsync(predicate, cancellationToken);
    }

    public async Task<int> CountAsync(CancellationToken cancellationToken = default)
    {
        return await _dbSet.CountAsync(cancellationToken);
    }

    public async Task<int> CountWhereAsync(Expression<Func<T, bool>> predicate, CancellationToken cancellationToken = default)
    {
        return await _dbSet.CountAsync(predicate, cancellationToken);
    }
}