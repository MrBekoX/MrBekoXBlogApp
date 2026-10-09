using BlogApp.Core.Domain.Entities;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Core.Application.Common.Interfaces.Data;

/// <summary>
/// Application DbContext arayüzü
/// </summary>
public interface IApplicationDbContext
{
    DbSet<BlogPost> Posts { get; }
    DbSet<Category> Categories { get; }
    DbSet<Tag> Tags { get; }
    DbSet<User> Users { get; }
    DbSet<Comment> Comments { get; }
    DbSet<RefreshToken> RefreshTokens { get; }

    Task<int> SaveChangesAsync(CancellationToken cancellationToken = default);
}

