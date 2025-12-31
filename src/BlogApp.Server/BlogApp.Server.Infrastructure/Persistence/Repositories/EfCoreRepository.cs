using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Domain.Common;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories;

public class EfCoreRepository<T> : IRepository<T> where T : BaseEntity
{
    protected readonly AppDbContext _context;
    protected DbSet<T> _dbSet => _context.Set<T>();

    public EfCoreRepository(AppDbContext context)
    {
        _context = context;
    }
}