using System.Data;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Npgsql;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Outbox;

/// <summary>
/// B3 test ortamı: docker compose postgres üzerinde İZOLE test veritabanı
/// (varsayılan blogdb_b3tests) kurar; migration'ları uygular; sınıflar arasında
/// tabloları temizler. Bağlantı bilgisi ortam değişkeni (BLOGAPP_TEST_PG_CONNECTION
/// veya BLOGAPP_TEST_PG_*) ile override edilebilir; aksi halde API'nin
/// appsettings.Development.json'ından (test çıktı dizinine kopyalanan) okunur.
/// Değerler log'a yazılmaz.
/// </summary>
public sealed class AgentOutboxDatabaseFixture : IAsyncLifetime
{
    public const string TestDatabaseName = "blogdb_b3tests";

    private string _devConnectionString = string.Empty;
    private string _testConnectionString = string.Empty;

    public string TestConnectionString => _testConnectionString;

    public async Task InitializeAsync()
    {
        _devConnectionString = ResolveDevConnectionString();

        var builder = new NpgsqlConnectionStringBuilder(_devConnectionString)
        {
            Database = "postgres",
        };

        await using (var maintenance = new NpgsqlConnection(builder.ConnectionString))
        {
            await maintenance.OpenAsync();

            // Kalıntı bağlantıları kes, veritabanını taze kur (her koşuda yalıtım).
            await ExecuteAsync(maintenance,
                $"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{TestDatabaseName}' AND pid <> pg_backend_pid()");
            await ExecuteAsync(maintenance, $"DROP DATABASE IF EXISTS \"{TestDatabaseName}\" WITH (FORCE)");
            await ExecuteAsync(maintenance, $"CREATE DATABASE \"{TestDatabaseName}\"");
        }

        _testConnectionString = new NpgsqlConnectionStringBuilder(_devConnectionString)
        {
            Database = TestDatabaseName,
        }.ConnectionString;

        await using (var context = CreateContext())
        {
            await context.Database.MigrateAsync();
        }
    }

    public async Task DisposeAsync()
    {
        var builder = new NpgsqlConnectionStringBuilder(_devConnectionString)
        {
            Database = "postgres",
        };

        await using var maintenance = new NpgsqlConnection(builder.ConnectionString);
        await maintenance.OpenAsync();
        await ExecuteAsync(maintenance,
            $"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{TestDatabaseName}' AND pid <> pg_backend_pid()");
        await ExecuteAsync(maintenance, $"DROP DATABASE IF EXISTS \"{TestDatabaseName}\" WITH (FORCE)");
    }

    public AppDbContext CreateContext() =>
        new(new DbContextOptionsBuilder<AppDbContext>()
            .UseNpgsql(_testConnectionString, npgsql =>
                npgsql.MigrationsAssembly(typeof(AppDbContext).Assembly.FullName))
            .Options);

    /// <summary>Sınıflar arası yalıtım: B3 tabloları + seed tabloları temizlenir.</summary>
    public async Task ResetAsync()
    {
        await using var context = CreateContext();
        await context.Database.ExecuteSqlRawAsync("""
            TRUNCATE outbox_messages, agent_runs, posts, users RESTART IDENTITY CASCADE
            """);
    }

    public async Task<User> SeedUserAsync(string userName = "agent-test-user")
    {
        await using var context = CreateContext();
        var user = new User
        {
            UserName = userName,
            Email = $"{userName}@example.com",
            PasswordHash = "test-only-not-a-secret",
        };
        context.Users.Add(user);
        await context.SaveChangesAsync();
        return user;
    }

    public async Task<BlogPost> SeedPostAsync(Guid authorId, string title, PostStatus status, long contentRevision = 0)
    {
        await using var context = CreateContext();
        var post = new BlogPost
        {
            Title = title,
            Slug = $"{title.ToLowerInvariant().Replace(' ', '-')}-{Guid.NewGuid().ToString("N")[..8]}",
            Content = $"# {title}\n\nBu B3 test içeriğidir. Agent soruları için kullanılır.",
            Status = status,
            AuthorId = authorId,
            ContentRevision = contentRevision,
        };
        if (status == PostStatus.Published)
        {
            post.Publish();
        }

        context.Posts.Add(post);
        await context.SaveChangesAsync();
        return post;
    }

    private static async Task ExecuteAsync(NpgsqlConnection connection, string sql)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = sql;
        await command.ExecuteNonQueryAsync();
    }

    private static string ResolveDevConnectionString()
    {
        var overrideConnection = Environment.GetEnvironmentVariable("BLOGAPP_TEST_PG_CONNECTION");
        if (!string.IsNullOrWhiteSpace(overrideConnection))
        {
            return overrideConnection;
        }

        var configuration = new Microsoft.Extensions.Configuration.ConfigurationBuilder()
            .SetBasePath(AppContext.BaseDirectory)
            .AddJsonFile("appsettings.Development.json", optional: true)
            .Build();

        var connectionString = configuration.GetConnectionString("DefaultConnection");
        if (string.IsNullOrWhiteSpace(connectionString))
        {
            throw new InvalidOperationException(
                "Postgres test bağlantısı bulunamadı: BLOGAPP_TEST_PG_CONNECTION tanımlı değil ve " +
                "appsettings.Development.json ConnectionStrings:DefaultConnection okunamadı. " +
                "docker compose postgres çalışıyor mu?");
        }

        return connectionString;
    }
}
