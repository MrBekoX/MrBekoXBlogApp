using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.Enums;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Infrastructure.Persistence;

public class DbSeeder
{
    private readonly ApplicationDbContext _context;
    private readonly IConfiguration _configuration;
    private readonly ILogger<DbSeeder> _logger;

    public DbSeeder(ApplicationDbContext context, IConfiguration configuration, ILogger<DbSeeder> logger)
    {
        _context = context;
        _configuration = configuration;
        _logger = logger;
    }

    public async Task SeedAsync()
    {
        try 
        {
            await SeedAdminUserAsync();
        }
        catch (Exception ex)
        {
            // Tablo henüz yoksa veya bağlantı hazır değilse uygulamanın çökmesini engeller
            _logger.LogWarning("Seeding failed: {Message}. This is expected if migrations are not yet applied.", ex.Message);
        }
    }

    private async Task SeedAdminUserAsync()
    {
        // ÖNEMLİ: .env dosyasındaki isimlerle tam uyum sağladık
        var adminEmail = _configuration["ADMIN_EMAIL"] ?? _configuration["AdminUser:Email"];
        var adminUserName = _configuration["ADMIN_USERNAME"] ?? _configuration["AdminUser:UserName"] ?? "admin";
        var adminPassword = _configuration["ADMIN_PASSWORD"] ?? _configuration["AdminUser:Password"];

        if (string.IsNullOrEmpty(adminEmail) || string.IsNullOrEmpty(adminPassword))
        {
            _logger.LogWarning("Admin credentials missing in .env (ADMIN_EMAIL, ADMIN_PASSWORD)");
            return;
        }

        // Tablo var mı kontrol et (Crash'i önler)
        var adminExists = await _context.Users
            .IgnoreQueryFilters()
            .AnyAsync(u => u.Role == UserRole.Admin);

        if (adminExists) return;

        var adminUser = new User
        {
            Id = Guid.NewGuid(),
            UserName = adminUserName,
            Email = adminEmail.ToLower(),
            PasswordHash = BCrypt.Net.BCrypt.HashPassword(adminPassword),
            FirstName = "Admin",
            LastName = "User",
            Role = UserRole.Admin,
            IsActive = true,
            CreatedAt = DateTime.UtcNow
        };

        await _context.Users.AddAsync(adminUser);
        await _context.SaveChangesAsync();
        _logger.LogInformation("Admin user created successfully!");
    }
}