using System.Data;
using BlogApp.Server.Application.Common.Interfaces.Persistence.BlogPostRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.CategoryRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.CommentRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.RefreshTokenRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.TagRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.UserRepository;

namespace BlogApp.Server.Application.Common.Interfaces.Persistence;

/// <summary>
/// Transaction scope interface'i - using block'unda kullanılabilir.
/// </summary>
public interface ITransactionScope : IDisposable, IAsyncDisposable
{
    Task CommitAsync(CancellationToken cancellationToken = default);
    Task RollbackAsync(CancellationToken cancellationToken = default);
}

/// <summary>
/// Unit of Work pattern arayüzü
/// </summary>
public interface IUnitOfWork : IAsyncDisposable, IDisposable
{
    // BlogPost Repositories
    IBlogPostReadRepository PostsRead { get; }
    IBlogPostWriteRepository PostsWrite { get; }

    // Category Repositories
    ICategoryReadRepository CategoriesRead { get; }
    ICategoryWriteRepository CategoriesWrite { get; }

    // Tag Repositories
    ITagReadRepository TagsRead { get; }
    ITagWriteRepository TagsWrite { get; }

    // User Repositories
    IUserReadRepository UsersRead { get; }
    IUserWriteRepository UsersWrite { get; }

    // Comment Repositories
    ICommentReadRepository CommentsRead { get; }
    ICommentWriteRepository CommentsWrite { get; }

    // RefreshToken Repositories
    IRefreshTokenReadRepository RefreshTokensRead { get; }
    IRefreshTokenWriteRepository RefreshTokensWrite { get; }

    // Transaction Management
    Task BeginTransactionAsync(CancellationToken cancellationToken = default);
    
    /// <summary>
    /// Belirtilen isolation level ile transaction başlatır.
    /// Race condition önleme gereken durumlarda (login, token refresh) Serializable kullanın.
    /// </summary>
    Task<ITransactionScope> BeginTransactionAsync(IsolationLevel isolationLevel, CancellationToken cancellationToken = default);
    
    Task CommitTransactionAsync(CancellationToken cancellationToken = default);
    Task RollbackTransactionAsync(CancellationToken cancellationToken = default);

    // Save Changes
    Task<int> SaveChangesAsync(CancellationToken cancellationToken = default);
}
