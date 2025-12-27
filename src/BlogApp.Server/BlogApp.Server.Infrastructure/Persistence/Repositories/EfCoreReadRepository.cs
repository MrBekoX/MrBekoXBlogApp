using System;
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

    public async Task<T?> GetByIdAsync(Guid id, CancellationToken cancellationToken = default)
    {
        return await _dbSet.FindAsync(new object[] { id }, cancellationToken);
    }

    public async Task<T?> GetAsync(Expression<Func<T, bool>> predicate, CancellationToken cancellationToken = default)
    {
        return await _dbSet.FirstOrDefaultAsync(predicate, cancellationToken);
    }

    public async Task<List<T>> GetAllAsync(CancellationToken cancellationToken = default)
    {
        return await _dbSet.ToListAsync(cancellationToken);
    }

    public async Task<List<T>> GetListAsync(Expression<Func<T, bool>> predicate, CancellationToken cancellationToken = default)
    {
        return await _dbSet.Where(predicate).ToListAsync(cancellationToken);
    }

    public async Task<bool> AnyAsync(Expression<Func<T, bool>> predicate, CancellationToken cancellationToken = default)
    {
        return await _dbSet.AnyAsync(predicate, cancellationToken);
    }

    public async Task<int> CountAsync(Expression<Func<T, bool>>? predicate = null, CancellationToken cancellationToken = default)
    {
        return predicate == null
            ? await _dbSet.CountAsync(cancellationToken)
            : await _dbSet.CountAsync(predicate, cancellationToken);
    }

    public IQueryable<T> Query()
    {
        return _dbSet.AsQueryable();
    }
}