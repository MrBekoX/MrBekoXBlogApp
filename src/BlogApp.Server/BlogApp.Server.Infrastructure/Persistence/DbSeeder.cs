using BlogApp.Server.Application.Common.Options;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.Enums;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace BlogApp.Server.Infrastructure.Persistence;

public class DbSeeder(
    AppDbContext context,
    IOptions<AdminUserSettings> adminUserSettings,
    ILogger<DbSeeder> logger)
{
    private readonly AdminUserSettings _adminSettings = adminUserSettings.Value;

    public async Task SeedAsync()
    {
        try
        {
            await SeedAdminUserAsync();
        }
        catch (Exception ex)
        {
            // Tablo henüz yoksa veya bağlantı hazır değilse uygulamanın çökmesini engeller
            logger.LogWarning("Seeding failed: {Message}. This is expected if migrations are not yet applied.", ex.Message);
        }
    }

    private async Task SeedAdminUserAsync()
    {
        // Production: .env veya appsettings'den al
        // Development: varsayılan değerler kullan
        var environment = Environment.GetEnvironmentVariable("ASPNETCORE_ENVIRONMENT") ?? "Production";
        var isDevelopment = environment == "Development";

        // Öncelik: Environment variables > Options (appsettings)
        var adminEmail = Environment.GetEnvironmentVariable("ADMIN_EMAIL") ?? _adminSettings.Email;
        var adminUserName = Environment.GetEnvironmentVariable("ADMIN_USERNAME") ?? _adminSettings.UserName ?? "admin";
        var adminPassword = Environment.GetEnvironmentVariable("ADMIN_PASSWORD") ?? _adminSettings.Password;

        // SECURITY: No hardcoded fallback passwords, even for development
        // Always require explicit configuration via environment variables
        if (string.IsNullOrEmpty(adminEmail) || string.IsNullOrEmpty(adminPassword))
        {
            if (isDevelopment)
            {
                logger.LogWarning("Missing ADMIN_EMAIL and ADMIN_PASSWORD environment variables in development.");
                logger.LogWarning("Please set these in your .env file:");
                logger.LogWarning("  ADMIN_EMAIL=admin@localhost");
                logger.LogWarning("  ADMIN_PASSWORD=YourSecurePassword123!@#");
            }
            else
            {
                logger.LogError("Missing ADMIN_EMAIL and ADMIN_PASSWORD environment variables in production!");
            }
            return;
        }

        // Check if admin user exists
        var existingAdmin = await context.Users
            .IgnoreQueryFilters()
            .FirstOrDefaultAsync(u => u.Role == UserRole.Admin);

        if (existingAdmin != null)
        {
            // Admin exists - sync password if changed
            var passwordMatches = BCrypt.Net.BCrypt.Verify(adminPassword, existingAdmin.PasswordHash);
            
            if (!passwordMatches)
            {
                existingAdmin.PasswordHash = BCrypt.Net.BCrypt.HashPassword(adminPassword);
                existingAdmin.UpdatedAt = DateTime.UtcNow;
                await context.SaveChangesAsync();
                logger.LogInformation("Admin password synced from environment variables.");
            }
            
            // Also sync email and username if changed
            var needsUpdate = false;
            if (existingAdmin.Email != adminEmail.ToLower())
            {
                existingAdmin.Email = adminEmail.ToLower();
                needsUpdate = true;
            }
            if (existingAdmin.UserName != adminUserName)
            {
                existingAdmin.UserName = adminUserName;
                needsUpdate = true;
            }
            if (needsUpdate)
            {
                existingAdmin.UpdatedAt = DateTime.UtcNow;
                await context.SaveChangesAsync();
                logger.LogInformation("Admin user info synced from environment variables.");
            }
            
            return;
        }

        // Create new admin if doesn't exist
        var adminUser = new User
        {
            Id = Guid.NewGuid(),
            UserName = adminUserName,
            Email = adminEmail.ToLower(),
            PasswordHash = BCrypt.Net.BCrypt.HashPassword(adminPassword),
            FirstName = _adminSettings.FirstName,
            LastName = "User",
            Role = UserRole.Admin,
            IsActive = true,
            CreatedAt = DateTime.UtcNow
        };

        await context.Users.AddAsync(adminUser);
        await context.SaveChangesAsync();
        logger.LogInformation("Admin user created successfully!");
    }
}
