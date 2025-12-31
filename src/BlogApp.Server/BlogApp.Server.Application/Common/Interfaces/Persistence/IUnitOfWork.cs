using BlogApp.Server.Application.Common.Interfaces.Persistence.BlogPostRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.CategoryRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.CommentRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.RefreshTokenRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.TagRepository;
using BlogApp.Server.Application.Common.Interfaces.Persistence.UserRepository;

namespace BlogApp.Server.Application.Common.Interfaces.Persistence;

/// <summary>
/// Unit of Work pattern arayüzü
/// </summary>
public interface IUnitOfWork : IAsyncDisposable
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
    Task CommitTransactionAsync(CancellationToken cancellationToken = default);
    Task RollbackTransactionAsync(CancellationToken cancellationToken = default);

    // Save Changes
    Task<int> SaveChangesAsync(CancellationToken cancellationToken = default);
}
