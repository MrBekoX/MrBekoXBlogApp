using System.Net.Mail;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace BlogApp.Infrastructure.Persistence;

/// <summary>Creates the first administrator without rotating or recovering existing accounts.</summary>
public sealed class DbSeeder(
    AppDbContext context,
    IOptions<AdminUserSettings> adminUserSettings,
    ILogger<DbSeeder> logger)
{
    private const long BootstrapLockKey = 0x424C4F4741444D;

    public async Task SeedAsync(CancellationToken cancellationToken = default)
    {
        // All replicas serialize the first-account decision. The execution strategy
        // owns the complete transaction so transient failures can safely retry it.
        var strategy = context.Database.CreateExecutionStrategy();
        await strategy.ExecuteAsync(async () =>
        {
            // A failed SaveChanges can leave this bootstrapper's attempted user
            // tracked as Added. A retry must rebuild its own fresh startup state.
            context.ChangeTracker.Clear();
            await using var transaction = await context.Database.BeginTransactionAsync(cancellationToken);
            await context.Database.ExecuteSqlInterpolatedAsync(
                $"SELECT pg_advisory_xact_lock({BootstrapLockKey})", cancellationToken);

            var administrators = context.Users.IgnoreQueryFilters().Where(user => user.Role == UserRole.Admin);
            if (await administrators.AnyAsync(user => user.IsActive && !user.IsDeleted, cancellationToken))
            {
                logger.LogInformation("Administrator bootstrap skipped; existing credentials and account settings were preserved.");
                await transaction.CommitAsync(cancellationToken);
                return;
            }
            if (await administrators.AnyAsync(cancellationToken))
            {
                throw new InvalidOperationException(
                    "An administrator exists but is inactive or deleted. Use explicit account recovery; bootstrap does not reactivate accounts.");
            }

            var settings = adminUserSettings.Value;
            var email = settings.Email?.Trim().ToLowerInvariant();
            var userName = string.IsNullOrWhiteSpace(settings.UserName) ? "admin" : settings.UserName.Trim();
            if (string.IsNullOrWhiteSpace(email) || email.Length > 256
                || !MailAddress.TryCreate(email, out var address) || address.Address != email
                || string.IsNullOrWhiteSpace(settings.Password) || userName.Length > 50
                || settings.FirstName.Length > 50)
            {
                throw new InvalidOperationException(
                    "Creating the first administrator requires valid AdminUser:Email and AdminUser:Password settings, a username of at most 50 characters, and a valid first name.");
            }

            var normalizedUserName = userName.ToLowerInvariant();
            if (await context.Users.IgnoreQueryFilters().AnyAsync(
                user => user.Email.ToLower() == email || user.UserName.ToLower() == normalizedUserName,
                cancellationToken))
            {
                throw new InvalidOperationException(
                    "Administrator bootstrap identity belongs to an existing account. Bootstrap does not promote or reuse accounts.");
            }

            context.Users.Add(new User
            {
                Id = Guid.NewGuid(),
                UserName = userName,
                Email = email,
                PasswordHash = BCrypt.Net.BCrypt.HashPassword(settings.Password, workFactor: 12),
                FirstName = settings.FirstName,
                LastName = "User",
                Role = UserRole.Admin,
                IsActive = true,
                CreatedAt = DateTime.UtcNow,
            });
            await context.SaveChangesAsync(cancellationToken);
            await transaction.CommitAsync(cancellationToken);
            logger.LogInformation("Initial administrator created. Subsequent startup does not rotate credentials.");
        });
    }
}
