using BlogApp.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Npgsql;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Cancel;

/// <summary>
/// B7 kontrol test ortamı: docker compose postgres üzerinde İZOLE test
/// veritabanı (blogdb_b7tests). Broker'a ihtiyaç duymaz: cancel komutu ve
/// reaper DB üstünde doğrulanır; broker taşıma akışları Python
/// tests/control paketindedir (L009 izolasyon kuralı).
/// </summary>
public sealed class AgentControlDatabaseFixture : IAsyncLifetime
{
    public const string TestDatabaseName = "blogdb_b7tests";

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
            await ExecuteAsync(maintenance,
                $"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{TestDatabaseName}' AND pid <> pg_backend_pid()");
            await ExecuteAsync(maintenance, $"DROP DATABASE IF EXISTS \"{TestDatabaseName}\" WITH (FORCE)");
            await ExecuteAsync(maintenance, $"CREATE DATABASE \"{TestDatabaseName}\"");
        }

        _testConnectionString = new NpgsqlConnectionStringBuilder(_devConnectionString)
        {
            Database = TestDatabaseName,
        }.ConnectionString;

        await using var context = CreateContext();
        await context.Database.MigrateAsync();
    }

    public async Task DisposeAsync()
    {
        // Test DB'sının havuz bağlantılarını istemci tarafında kapat: DROP,
        // canlı Npgsql havuzuyla yarışmasın (tam suite koşumunda gözlenen
        // cleanup yarışı).
        NpgsqlConnection.ClearAllPools();

        var builder = new NpgsqlConnectionStringBuilder(_devConnectionString)
        {
            Database = "postgres",
        };
        await using var maintenance = new NpgsqlConnection(builder.ConnectionString);
        await maintenance.OpenAsync();
        await ExecuteAsync(maintenance,
            $"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{TestDatabaseName}' AND pid <> pg_backend_pid()");

        // DROP, backend sonlanmasının yayılmasıyla yarışabilir (tam suite
        // sonunda aralıklı NpgsqlException): sınırlı, artan beklemeli tekrar.
        for (var attempt = 0; ; attempt++)
        {
            try
            {
                await ExecuteAsync(maintenance, $"DROP DATABASE IF EXISTS \"{TestDatabaseName}\" WITH (FORCE)");
                return;
            }
            catch (NpgsqlException) when (attempt < 3)
            {
                await Task.Delay(300 * (attempt + 1));
            }
        }
    }

    public AppDbContext CreateContext() =>
        new(new DbContextOptionsBuilder<AppDbContext>()
            .UseNpgsql(_testConnectionString, npgsql =>
                npgsql.MigrationsAssembly(typeof(AppDbContext).Assembly.FullName))
            .Options);

    public async Task ResetAsync()
    {
        await using var context = CreateContext();
        await context.Database.ExecuteSqlRawAsync("TRUNCATE outbox_messages, agent_runs RESTART IDENTITY CASCADE");
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

        var configuration = new ConfigurationBuilder()
            .SetBasePath(AppContext.BaseDirectory)
            .AddJsonFile("appsettings.Development.json", optional: true)
            .Build();

        var connectionString = configuration.GetConnectionString("DefaultConnection");
        if (string.IsNullOrWhiteSpace(connectionString))
        {
            throw new InvalidOperationException(
                "Postgres test bağlantısı bulunamadı: BLOGAPP_TEST_PG_CONNECTION tanımlı değil ve " +
                "appsettings.Development.json ConnectionStrings:DefaultConnection okunamadı.");
        }

        return connectionString;
    }
}

/// <summary>B7 kontrol test koleksiyonu: postgres fixture'ı paylaşılır.</summary>
[CollectionDefinition("agent-b7-control")]
public sealed class AgentControlCollection : ICollectionFixture<AgentControlDatabaseFixture>
{
}
