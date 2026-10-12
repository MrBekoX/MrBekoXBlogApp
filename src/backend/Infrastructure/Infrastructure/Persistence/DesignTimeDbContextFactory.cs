using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;

namespace BlogApp.Infrastructure.Persistence;

/// <summary>
/// dotnet ef tasarım zamanı context fabrikası (B3). Runtime davranışını değiştirmez;
/// yalnız host açılamadığında EF araçlarının yedeğidir. Bağlantı bilgisi
/// BLOGAPP_MIGRATION_CONNECTION ortam değişkeninden okunur; değeri log'a yazılmaz.
/// </summary>
public sealed class DesignTimeDbContextFactory : IDesignTimeDbContextFactory<AppDbContext>
{
    public AppDbContext CreateDbContext(string[] args)
    {
        var connectionString = Environment.GetEnvironmentVariable("BLOGAPP_MIGRATION_CONNECTION");
        if (string.IsNullOrWhiteSpace(connectionString))
        {
            throw new InvalidOperationException(
                "Tasarım zamanı DbContext için BLOGAPP_MIGRATION_CONNECTION ortam değişkeni gereklidir.");
        }

        var options = new DbContextOptionsBuilder<AppDbContext>()
            .UseNpgsql(connectionString, npgsql =>
                npgsql.MigrationsAssembly(typeof(AppDbContext).Assembly.FullName))
            .Options;

        return new AppDbContext(options);
    }
}
