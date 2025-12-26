using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.Enums;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Infrastructure.Persistence;

/// <summary>
/// Veritabanı seed işlemleri için servis.
/// Admin kullanıcı oluşturma gibi hassas işlemler için environment variable kullanır.
/// </summary>
public class DbSeeder
{
    private readonly ApplicationDbContext _context;
    private readonly IConfiguration _configuration;
    private readonly ILogger<DbSeeder> _logger;

    public DbSeeder(
        ApplicationDbContext context,
        IConfiguration configuration,
        ILogger<DbSeeder> logger)
    {
        _context = context;
        _configuration = configuration;
        _logger = logger;
    }

    public async Task SeedAsync()
    {
        await SeedAdminUserAsync();
    }

    private async Task SeedAdminUserAsync()
    {
        // Admin zaten varsa atla
        var adminExists = await _context.Users
            .IgnoreQueryFilters()
            .AnyAsync(u => u.Role == UserRole.Admin);

        if (adminExists)
        {
            _logger.LogInformation("Admin user already exists, skipping seed");
            return;
        }

        // Admin bilgilerini configuration'dan al
        var adminEmail = _configuration["AdminUser:Email"];
        var adminUserName = _configuration["AdminUser:UserName"];
        var adminPassword = _configuration["AdminUser:Password"];
        var adminFirstName = _configuration["AdminUser:FirstName"] ?? "Admin";

        // Gerekli değerler yoksa uyarı ver ve çık
        if (string.IsNullOrEmpty(adminEmail) ||
            string.IsNullOrEmpty(adminUserName) ||
            string.IsNullOrEmpty(adminPassword))
        {
            _logger.LogWarning(
                "Admin user credentials not configured. " +
                "Set AdminUser:Email, AdminUser:UserName, and AdminUser:Password in configuration or environment variables. " +
                "Example: AdminUser__Email, AdminUser__UserName, AdminUser__Password");
            return;
        }

        // Şifre güvenlik kontrolü
        if (adminPassword.Length < 12)
        {
            _logger.LogError("Admin password must be at least 12 characters long");
            return;
        }

        var adminUser = new User
        {
            Id = Guid.NewGuid(),
            UserName = adminUserName,
            Email = adminEmail.ToLower(),
            PasswordHash = BCrypt.Net.BCrypt.HashPassword(adminPassword),
            FirstName = adminFirstName,
            LastName = "",
            Role = UserRole.Admin,
            IsActive = true,
            CreatedAt = DateTime.UtcNow,
            IsDeleted = false,
            FailedLoginAttempts = 0
        };

        await _context.Users.AddAsync(adminUser);
        await _context.SaveChangesAsync();

        _logger.LogInformation("Admin user created successfully: {UserName}", adminUserName);
    }
}
