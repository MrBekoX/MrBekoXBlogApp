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

        // Development ortamında varsayılan değerler kullan
        if (isDevelopment && string.IsNullOrEmpty(adminEmail))
        {
            adminEmail = "admin@blogapp.local";
            adminPassword = "Admin123!@#";
            logger.LogInformation("Using default admin credentials for development");
        }

        if (string.IsNullOrEmpty(adminEmail) || string.IsNullOrEmpty(adminPassword))
        {
            logger.LogWarning("Admin credentials missing in .env (ADMIN_EMAIL, ADMIN_PASSWORD)");
            return;
        }

        // Tablo var mı kontrol et (Crash'i önler)
        var adminExists = await context.Users
            .IgnoreQueryFilters()
            .AnyAsync(u => u.Role == UserRole.Admin);

        if (adminExists) return;

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
