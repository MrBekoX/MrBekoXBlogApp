using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Interfaces;

/// <summary>
/// Unit of Work pattern arayüzü
/// </summary>
public interface IUnitOfWork : IAsyncDisposable
{
    IReadRepository<BlogPost> PostsRead { get; }
    IWriteRepository<BlogPost> PostsWrite { get; }
    
    IReadRepository<Category> CategoriesRead { get; }
    IWriteRepository<Category> CategoriesWrite { get; }
    
    IReadRepository<Tag> TagsRead { get; }
    IWriteRepository<Tag> TagsWrite { get; }
    
    IReadRepository<User> UsersRead { get; }
    IWriteRepository<User> UsersWrite { get; }
    
    IReadRepository<Comment> CommentsRead { get; }
    IWriteRepository<Comment> CommentsWrite { get; }
    
    IReadRepository<RefreshToken> RefreshTokensRead { get; }
    IWriteRepository<RefreshToken> RefreshTokensWrite { get; }

    Task<int> SaveChangesAsync(CancellationToken cancellationToken = default);
    Task BeginTransactionAsync(CancellationToken cancellationToken = default);
    Task CommitTransactionAsync(CancellationToken cancellationToken = default);
    Task RollbackTransactionAsync(CancellationToken cancellationToken = default);
}