using BlogApp.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Npgsql;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Agent;

/// <summary>
/// B10 endpoint destek test ortamı: docker compose postgres üzerinde İZOLE test
/// veritabanı (L009: her faz kendi scratch DB'sini kullanır). DB adı SÜREÇ BAŞINA
/// benzersizdir (``blogdb_b10tests_p{pid}``): iki test süreci (ör. B9 fazı ile bu
/// fazın doğrulaması) aynı suite'i eşzamanlı koşturduğunda birbirinin DB'sini
/// DROP etmez — orchestrator koşumunda gözlenen 42P01/57P01 çapraz-süreç yarışına
/// karşı B10 koleksiyonunu bağışık kılar. Çöken koşumlar kendi DB'sini bırakabilir
/// (dev scratch ortamı; Dispose yalnız KENDİ DB'sini düşürür).
/// Broker'a ihtiyaç duymaz: durum/replay/feedback/resume/gözlem sorguları backend
/// projection ve outbox tabloları üstünde doğrulanır; endpoint ince katmanı
/// (mediatR çağrısı + 202 eşlemesi) handler testleriyle aynı yolları kullanır.
/// </summary>
public sealed class AgentB10DatabaseFixture : IAsyncLifetime
{
    public static readonly string TestDatabaseName =
        $"blogdb_b10tests_p{Environment.ProcessId}";

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
        NpgsqlConnection.ClearAllPools();

        var builder = new NpgsqlConnectionStringBuilder(_devConnectionString)
        {
            Database = "postgres",
        };
        await using var maintenance = new NpgsqlConnection(builder.ConnectionString);
        await maintenance.OpenAsync();
        await ExecuteAsync(maintenance,
            $"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{TestDatabaseName}' AND pid <> pg_backend_pid()");

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
        await context.Database.ExecuteSqlRawAsync(
            "TRUNCATE outbox_messages, agent_runs, agent_event_inbox RESTART IDENTITY CASCADE");
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

/// <summary>B10 test koleksiyonu: postgres fixture'ı paylaşılır (seri koşum güvenli).</summary>
[CollectionDefinition("agent-b10")]
public sealed class AgentB10Collection : ICollectionFixture<AgentB10DatabaseFixture>
{
}
