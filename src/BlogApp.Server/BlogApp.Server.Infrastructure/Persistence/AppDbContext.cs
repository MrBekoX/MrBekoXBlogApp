using System.Reflection;
using BlogApp.Server.Application.Common.Interfaces.Data;
using BlogApp.Server.Domain.Common;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.Enums;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Infrastructure.Persistence;

/// <summary>
/// Application DbContext implementasyonu
/// </summary>
public class AppDbContext : DbContext, IApplicationDbContext
{
    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options)
    {
    }

    public DbSet<BlogPost> Posts => Set<BlogPost>();
    public DbSet<Category> Categories => Set<Category>();
    public DbSet<Tag> Tags => Set<Tag>();
    public DbSet<User> Users => Set<User>();
    public DbSet<Comment> Comments => Set<Comment>();
    public DbSet<RefreshToken> RefreshTokens => Set<RefreshToken>();
    public DbSet<IdempotencyRecord> IdempotencyRecords => Set<IdempotencyRecord>();
    public DbSet<OutboxMessage> OutboxMessages => Set<OutboxMessage>();
    public DbSet<ConsumerInboxMessage> ConsumerInboxMessages => Set<ConsumerInboxMessage>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        // TÃ¼m configuration'larÄ± uygula
        modelBuilder.ApplyConfigurationsFromAssembly(Assembly.GetExecutingAssembly());

        // Global query filter for soft delete
        modelBuilder.Entity<BlogPost>().HasQueryFilter(p => !p.IsDeleted);
        modelBuilder.Entity<Category>().HasQueryFilter(c => !c.IsDeleted);
        modelBuilder.Entity<Tag>().HasQueryFilter(t => !t.IsDeleted);
        modelBuilder.Entity<User>().HasQueryFilter(u => !u.IsDeleted);
        modelBuilder.Entity<Comment>().HasQueryFilter(c => !c.IsDeleted);
        modelBuilder.Entity<RefreshToken>().HasQueryFilter(r => r.User != null && !r.User.IsDeleted);
        modelBuilder.Entity<IdempotencyRecord>().HasQueryFilter(r => !r.IsDeleted);
        modelBuilder.Entity<OutboxMessage>().HasQueryFilter(m => !m.IsDeleted);
        modelBuilder.Entity<ConsumerInboxMessage>().HasQueryFilter(m => !m.IsDeleted);
    }

    public override async Task<int> SaveChangesAsync(CancellationToken cancellationToken = default)
    {
        foreach (var entry in ChangeTracker.Entries<BaseAuditableEntity>())
        {
            switch (entry.State)
            {
                case EntityState.Added:
                    entry.Entity.CreatedAt = DateTime.UtcNow;
                    entry.Entity.UpdatedAt = DateTime.UtcNow;
                    break;
                case EntityState.Modified:
                    entry.Entity.UpdatedAt = DateTime.UtcNow;
                    break;
            }
        }

        return await base.SaveChangesAsync(cancellationToken);
    }
}
