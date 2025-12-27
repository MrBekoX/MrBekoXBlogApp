using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Domain.Common;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories;

/// <summary>
/// Generic EF Core Repository implementasyonu
/// Read ve Write işlemlerini ayrı repository'ler üzerinden yapar
/// </summary>
public class EfCoreRepository<T>(AppDbContext context) 
    where T : BaseEntity
{
    protected readonly DbSet<T> _dbSet = context.Set<T>();
}