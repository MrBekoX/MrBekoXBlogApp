using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Domain.Entities;
using Microsoft.EntityFrameworkCore.Storage;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories;

/// <summary>
/// Unit of Work pattern implementasyonu
/// </summary>
public class UnitOfWork(ApplicationDbContext context) : IUnitOfWork
{
    private IDbContextTransaction? _transaction;

    private IRepository<BlogPost>? _posts;
    private IRepository<Category>? _categories;
    private IRepository<Tag>? _tags;
    private IRepository<User>? _users;
    private IRepository<Comment>? _comments;
    private IRepository<RefreshToken>? _refreshTokens;

    public IRepository<BlogPost> Posts =>
        _posts ??= new EfCoreRepository<BlogPost>(context);

    public IRepository<Category> Categories =>
        _categories ??= new EfCoreRepository<Category>(context);

    public IRepository<Tag> Tags =>
        _tags ??= new EfCoreRepository<Tag>(context);

    public IRepository<User> Users =>
        _users ??= new EfCoreRepository<User>(context);

    public IRepository<Comment> Comments =>
        _comments ??= new EfCoreRepository<Comment>(context);

    public IRepository<RefreshToken> RefreshTokens =>
        _refreshTokens ??= new EfCoreRepository<RefreshToken>(context);

    public async Task<int> SaveChangesAsync(CancellationToken cancellationToken = default)
    {
        return await context.SaveChangesAsync(cancellationToken);
    }

    public async Task BeginTransactionAsync(CancellationToken cancellationToken = default)
    {
        _transaction = await context.Database.BeginTransactionAsync(cancellationToken);
    }

    public async Task CommitTransactionAsync(CancellationToken cancellationToken = default)
    {
        if (_transaction is not null)
        {
            await _transaction.CommitAsync(cancellationToken);
            await _transaction.DisposeAsync();
            _transaction = null;
        }
    }

    public async Task RollbackTransactionAsync(CancellationToken cancellationToken = default)
    {
        if (_transaction is not null)
        {
            await _transaction.RollbackAsync(cancellationToken);
            await _transaction.DisposeAsync();
            _transaction = null;
        }
    }

    public async ValueTask DisposeAsync()
    {
        // Transaction varsa dispose et
        if (_transaction is not null)
        {
            await _transaction.DisposeAsync();
            _transaction = null;
        }

        // Context'i dispose et
        await context.DisposeAsync();
    }
}