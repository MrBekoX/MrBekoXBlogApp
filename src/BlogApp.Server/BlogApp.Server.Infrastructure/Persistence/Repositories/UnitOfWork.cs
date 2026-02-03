using System.Data;
using BlogApp.Server.Application.Common.Interfaces.Persistence.BlogPostRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.CategoryRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.CommentRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.RefreshTokenRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.TagRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.UserRepository;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Infrastructure.Persistence;
using BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreBlogPostRepository;
using BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreCategoryRepository;
using BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreCommentRepository;
using BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreRefreshTokenRepository;
using BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreTagRepository;
using BlogApp.Server.Infrastructure.Persistence.Repositories.EfCoreUserRepository;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;

namespace BlogApp.Server.Infrastructure.Persistence.Repositories;

/// <summary>
/// Unit of Work pattern implementasyonu
/// </summary>
public class UnitOfWork(AppDbContext context) : Application.Common.Interfaces.Persistence.IUnitOfWork
{
    private IDbContextTransaction? _transaction;

    // Read Repositories
    private IBlogPostReadRepository? _postsRead;
    private ICategoryReadRepository? _categoriesRead;
    private ITagReadRepository? _tagsRead;
    private IUserReadRepository? _usersRead;
    private ICommentReadRepository? _commentsRead;
    private IRefreshTokenReadRepository? _refreshTokensRead;

    // Write Repositories
    private IBlogPostWriteRepository? _postsWrite;
    private ICategoryWriteRepository? _categoriesWrite;
    private ITagWriteRepository? _tagsWrite;
    private IUserWriteRepository? _usersWrite;
    private ICommentWriteRepository? _commentsWrite;
    private IRefreshTokenWriteRepository? _refreshTokensWrite;

    public IBlogPostReadRepository PostsRead =>
        _postsRead ??= new EfCoreBlogPostReadRepository(context);

    public IBlogPostWriteRepository PostsWrite =>
        _postsWrite ??= new EfCoreBlogPostWriteRepository(context);

    public ICategoryReadRepository CategoriesRead =>
        _categoriesRead ??= new EfCoreCategoryReadRepository(context);

    public ICategoryWriteRepository CategoriesWrite =>
        _categoriesWrite ??= new EfCoreCategoryWriteRepository(context);

    public ITagReadRepository TagsRead =>
        _tagsRead ??= new EfCoreTagReadRepository(context);

    public ITagWriteRepository TagsWrite =>
        _tagsWrite ??= new EfCoreTagWriteRepository(context);

    public IUserReadRepository UsersRead =>
        _usersRead ??= new EfCoreUserReadRepository(context);

    public IUserWriteRepository UsersWrite =>
        _usersWrite ??= new EfCoreUserWriteRepository(context);

    public ICommentReadRepository CommentsRead =>
        _commentsRead ??= new EfCoreCommentReadRepository(context);

    public ICommentWriteRepository CommentsWrite =>
        _commentsWrite ??= new EfCoreCommentWriteRepository(context);

    public IRefreshTokenReadRepository RefreshTokensRead =>
        _refreshTokensRead ??= new EfCoreRefreshTokenReadRepository(context);

    public IRefreshTokenWriteRepository RefreshTokensWrite =>
        _refreshTokensWrite ??= new EfCoreRefreshTokenWriteRepository(context);

    public async Task<int> SaveChangesAsync(CancellationToken cancellationToken = default)
    {
        return await context.SaveChangesAsync(cancellationToken);
    }

    public async Task BeginTransactionAsync(CancellationToken cancellationToken = default)
    {
        _transaction = await context.Database.BeginTransactionAsync(cancellationToken);
    }

    /// <summary>
    /// Belirtilen isolation level ile transaction başlatır ve ITransactionScope wrapper döner.
    /// Race condition önleme gereken durumlarda (login, token refresh) Serializable kullanın.
    /// </summary>
    public async Task<Application.Common.Interfaces.Persistence.ITransactionScope> BeginTransactionAsync(IsolationLevel isolationLevel, CancellationToken cancellationToken = default)
    {
        _transaction = await context.Database.BeginTransactionAsync(isolationLevel, cancellationToken);
        return new TransactionWrapper(_transaction);
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
        if (_transaction is not null)
        {
            await _transaction.DisposeAsync();
            _transaction = null;
        }

        await context.DisposeAsync();
    }

    public void Dispose()
    {
        _transaction?.Dispose();
        _transaction = null;
        context.Dispose();
    }
}

/// <summary>
/// IDbContextTransaction için ITransactionScope wrapper.
/// Transaction'ın using block'unda kullanılmasını sağlar.
/// </summary>
internal sealed class TransactionWrapper : Application.Common.Interfaces.Persistence.ITransactionScope
{
    private readonly IDbContextTransaction _transaction;
    private bool _disposed;

    public TransactionWrapper(IDbContextTransaction transaction)
    {
        _transaction = transaction;
    }

    public async Task CommitAsync(CancellationToken cancellationToken = default)
    {
        await _transaction.CommitAsync(cancellationToken);
    }

    public async Task RollbackAsync(CancellationToken cancellationToken = default)
    {
        await _transaction.RollbackAsync(cancellationToken);
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _transaction.Dispose();
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed) return;
        _disposed = true;
        await _transaction.DisposeAsync();
    }
}