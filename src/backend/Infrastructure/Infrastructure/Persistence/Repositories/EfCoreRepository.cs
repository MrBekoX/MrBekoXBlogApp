using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Domain.Common;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Infrastructure.Persistence.Repositories;

public class EfCoreRepository<T> : IRepository<T> where T : BaseEntity
{
    protected readonly AppDbContext _context;
    protected DbSet<T> _dbSet => _context.Set<T>();

    public EfCoreRepository(AppDbContext context)
    {
        _context = context;
    }
}