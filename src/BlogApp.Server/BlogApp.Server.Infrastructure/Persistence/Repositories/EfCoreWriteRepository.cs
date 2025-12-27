using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Domain.Common;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories;

/// <summary>
/// Generic EF Core Write Repository implementasyonu
/// </summary>
public class EfCoreWriteRepository<T> :EfCoreRepository<T>, IWriteRepository<T> where T : BaseEntity
{
    
    public EfCoreWriteRepository(AppDbContext context) : base(context)
    {
    }

    
    public async Task<T> AddAsync(T entity, CancellationToken cancellationToken = default)
    {
    
        await _dbSet.AddAsync(entity, cancellationToken);
        return entity;
    }

    public async Task AddRangeAsync(IEnumerable<T> entities, CancellationToken cancellationToken = default)
    {
        await _dbSet.AddRangeAsync(entities, cancellationToken);
    }

    public void Update(T entity)
    {
        _dbSet.Update(entity);
    }

    public void UpdateRange(IEnumerable<T> entities)
    {
        _dbSet.UpdateRange(entities);
    }

    public void Delete(T entity)
    {
        _dbSet.Remove(entity);
    }

    public void DeleteRange(IEnumerable<T> entities)
    {
        _dbSet.RemoveRange(entities);
    }
}