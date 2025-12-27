using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Common.Interfaces;

/// <summary>
/// Unit of Work pattern arayüzü
/// </summary>
public interface IUnitOfWork : IAsyncDisposable
{
    IRepository<BlogPost> Posts { get; }
    IRepository<Category> Categories { get; }
    IRepository<Tag> Tags { get; }
    IRepository<User> Users { get; }
    IRepository<Comment> Comments { get; }
    IRepository<RefreshToken> RefreshTokens { get; }

    Task<int> SaveChangesAsync(CancellationToken cancellationToken = default);
    Task BeginTransactionAsync(CancellationToken cancellationToken = default);
    Task CommitTransactionAsync(CancellationToken cancellationToken = default);
    Task RollbackTransactionAsync(CancellationToken cancellationToken = default);
}
