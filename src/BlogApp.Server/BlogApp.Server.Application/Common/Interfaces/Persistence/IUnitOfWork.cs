using System.Data;
using BlogApp.Server.Application.Common.Interfaces.Persistence.BlogPostRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.CategoryRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.CommentRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.RefreshTokenRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.TagRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.UserRepository;

namespace BlogApp.Server.Application.Common.Interfaces.Persistence;

/// <summary>
/// Transaction scope interface for using-block transaction management.
/// </summary>
public interface ITransactionScope : IDisposable, IAsyncDisposable
{
    Task CommitAsync(CancellationToken cancellationToken = default);
    Task RollbackAsync(CancellationToken cancellationToken = default);
}

/// <summary>
/// Unit of Work abstraction.
/// </summary>
public interface IUnitOfWork : IAsyncDisposable, IDisposable
{
    IBlogPostReadRepository PostsRead { get; }
    IBlogPostWriteRepository PostsWrite { get; }
    ICategoryReadRepository CategoriesRead { get; }
    ICategoryWriteRepository CategoriesWrite { get; }
    ITagReadRepository TagsRead { get; }
    ITagWriteRepository TagsWrite { get; }
    IUserReadRepository UsersRead { get; }
    IUserWriteRepository UsersWrite { get; }
    ICommentReadRepository CommentsRead { get; }
    ICommentWriteRepository CommentsWrite { get; }
    IRefreshTokenReadRepository RefreshTokensRead { get; }
    IRefreshTokenWriteRepository RefreshTokensWrite { get; }

    Task BeginTransactionAsync(CancellationToken cancellationToken = default);
    Task<ITransactionScope> BeginTransactionAsync(IsolationLevel isolationLevel, CancellationToken cancellationToken = default);
    Task CommitTransactionAsync(CancellationToken cancellationToken = default);
    Task RollbackTransactionAsync(CancellationToken cancellationToken = default);
    Task<TResult> ExecuteResilientAsync<TResult>(Func<CancellationToken, Task<TResult>> operation, CancellationToken cancellationToken = default);
    Task<int> SaveChangesAsync(CancellationToken cancellationToken = default);
}