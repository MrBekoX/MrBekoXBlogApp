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
    DbSet<IdempotencyRecord> IdempotencyRecords { get; }

    /// <summary>Agent iş kabul kayıtları (B3).</summary>
    DbSet<AgentRun> AgentRuns { get; }

    /// <summary>Agent olay tüketim idempotency kayıtları (B5).</summary>
    DbSet<AgentEventInbox> AgentEventInboxes { get; }

    /// <summary>Transactional outbox kayıtları (B3).</summary>
    DbSet<OutboxMessage> OutboxMessages { get; }

    Task<int> SaveChangesAsync(CancellationToken cancellationToken = default);
}
