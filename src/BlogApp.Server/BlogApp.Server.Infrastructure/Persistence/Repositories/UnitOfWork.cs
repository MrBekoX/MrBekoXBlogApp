using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore.Storage;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories;

/// <summary>
/// Unit of Work pattern implementasyonu
/// </summary>
public class UnitOfWork(AppDbContext context) : IUnitOfWork
{
    private IDbContextTransaction? _transaction;

    // Read Repositories
    private IReadRepository<BlogPost>? _postsRead;
    private IReadRepository<Category>? _categoriesRead;
    private IReadRepository<Tag>? _tagsRead;
    private IReadRepository<User>? _usersRead;
    private IReadRepository<Comment>? _commentsRead;
    private IReadRepository<RefreshToken>? _refreshTokensRead;

    // Write Repositories
    private IWriteRepository<BlogPost>? _postsWrite;
    private IWriteRepository<Category>? _categoriesWrite;
    private IWriteRepository<Tag>? _tagsWrite;
    private IWriteRepository<User>? _usersWrite;
    private IWriteRepository<Comment>? _commentsWrite;
    private IWriteRepository<RefreshToken>? _refreshTokensWrite;

    public IReadRepository<BlogPost> PostsRead =>
        _postsRead ??= new EfCoreReadRepository<BlogPost>(context);

    public IWriteRepository<BlogPost> PostsWrite =>
        _postsWrite ??= new EfCoreWriteRepository<BlogPost>(context);

    public IReadRepository<Category> CategoriesRead =>
        _categoriesRead ??= new EfCoreReadRepository<Category>(context);

    public IWriteRepository<Category> CategoriesWrite =>
        _categoriesWrite ??= new EfCoreWriteRepository<Category>(context);

    public IReadRepository<Tag> TagsRead =>
        _tagsRead ??= new EfCoreReadRepository<Tag>(context);

    public IWriteRepository<Tag> TagsWrite =>
        _tagsWrite ??= new EfCoreWriteRepository<Tag>(context);

    public IReadRepository<User> UsersRead =>
        _usersRead ??= new EfCoreReadRepository<User>(context);

    public IWriteRepository<User> UsersWrite =>
        _usersWrite ??= new EfCoreWriteRepository<User>(context);

    public IReadRepository<Comment> CommentsRead =>
        _commentsRead ??= new EfCoreReadRepository<Comment>(context);

    public IWriteRepository<Comment> CommentsWrite =>
        _commentsWrite ??= new EfCoreWriteRepository<Comment>(context);

    public IReadRepository<RefreshToken> RefreshTokensRead =>
        _refreshTokensRead ??= new EfCoreReadRepository<RefreshToken>(context);

    public IWriteRepository<RefreshToken> RefreshTokensWrite =>
        _refreshTokensWrite ??= new EfCoreWriteRepository<RefreshToken>(context);

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