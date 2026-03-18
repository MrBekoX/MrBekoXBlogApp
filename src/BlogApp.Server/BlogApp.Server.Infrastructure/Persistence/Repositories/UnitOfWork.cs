using System.Data;
using BlogApp.Server.Application.Common.Interfaces.Persistence.BlogPostRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.CategoryRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.CommentRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.RefreshTokenRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.TagRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.UserRepository;
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

public class UnitOfWork(AppDbContext context) : Application.Common.Interfaces.Persistence.IUnitOfWork
{
    private IDbContextTransaction? _transaction;

    private IBlogPostReadRepository? _postsRead;
    private ICategoryReadRepository? _categoriesRead;
    private ITagReadRepository? _tagsRead;
    private IUserReadRepository? _usersRead;
    private ICommentReadRepository? _commentsRead;
    private IRefreshTokenReadRepository? _refreshTokensRead;

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

    public Task<int> SaveChangesAsync(CancellationToken cancellationToken = default)
    {
        return context.SaveChangesAsync(cancellationToken);
    }

    public async Task BeginTransactionAsync(CancellationToken cancellationToken = default)
    {
        _transaction = await context.Database.BeginTransactionAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<Application.Common.Interfaces.Persistence.ITransactionScope> BeginTransactionAsync(
        IsolationLevel isolationLevel,
        CancellationToken cancellationToken = default)
    {
        _transaction = await context.Database.BeginTransactionAsync(isolationLevel, cancellationToken).ConfigureAwait(false);
        return new TransactionWrapper(_transaction);
    }

    public async Task CommitTransactionAsync(CancellationToken cancellationToken = default)
    {
        if (_transaction is null)
        {
            return;
        }

        await _transaction.CommitAsync(cancellationToken).ConfigureAwait(false);
        await _transaction.DisposeAsync().ConfigureAwait(false);
        _transaction = null;
    }

    public async Task RollbackTransactionAsync(CancellationToken cancellationToken = default)
    {
        if (_transaction is null)
        {
            return;
        }

        await _transaction.RollbackAsync(cancellationToken).ConfigureAwait(false);
        await _transaction.DisposeAsync().ConfigureAwait(false);
        _transaction = null;
    }

    public Task<TResult> ExecuteResilientAsync<TResult>(
        Func<CancellationToken, Task<TResult>> operation,
        CancellationToken cancellationToken = default)
    {
        var strategy = context.Database.CreateExecutionStrategy();
        return strategy.ExecuteAsync(() => operation(cancellationToken));
    }

    public async ValueTask DisposeAsync()
    {
        if (_transaction is not null)
        {
            await _transaction.DisposeAsync().ConfigureAwait(false);
            _transaction = null;
        }

        await context.DisposeAsync().ConfigureAwait(false);
    }

    public void Dispose()
    {
        _transaction?.Dispose();
        _transaction = null;
        context.Dispose();
    }
}

internal sealed class TransactionWrapper : Application.Common.Interfaces.Persistence.ITransactionScope
{
    private readonly IDbContextTransaction _transaction;
    private bool _disposed;
    private bool _committed;
    private bool _rolledBack;

    public TransactionWrapper(IDbContextTransaction transaction)
    {
        _transaction = transaction;
    }

    public async Task CommitAsync(CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();

        if (_rolledBack)
        {
            throw new InvalidOperationException("Transaction cannot be committed after rollback.");
        }

        if (_committed)
        {
            throw new InvalidOperationException("Transaction has already been committed.");
        }

        await _transaction.CommitAsync(cancellationToken).ConfigureAwait(false);
        _committed = true;
    }

    public async Task RollbackAsync(CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();

        if (_committed)
        {
            throw new InvalidOperationException("Transaction cannot be rolled back after commit.");
        }

        if (_rolledBack)
        {
            return;
        }

        await _transaction.RollbackAsync(cancellationToken).ConfigureAwait(false);
        _rolledBack = true;
    }

    private void ThrowIfDisposed()
    {
        if (_disposed)
        {
            throw new ObjectDisposedException(nameof(TransactionWrapper));
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;

        if (!_committed && !_rolledBack)
        {
            try
            {
                _transaction.Rollback();
            }
            catch
            {
            }
        }

        _transaction.Dispose();
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;

        if (!_committed && !_rolledBack)
        {
            try
            {
                await _transaction.RollbackAsync().ConfigureAwait(false);
            }
            catch
            {
            }
        }

        await _transaction.DisposeAsync().ConfigureAwait(false);
    }
}