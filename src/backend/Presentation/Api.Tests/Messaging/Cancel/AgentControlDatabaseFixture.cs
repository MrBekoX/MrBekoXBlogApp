using BlogApp.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Npgsql;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Cancel;

/// <summary>
/// B7 kontrol test ortamı: docker compose postgres üzerinde İZOLE test
/// veritabanı. Broker'a ihtiyaç duymaz: cancel komutu ve
/// reaper DB üstünde doğrulanır; broker taşıma akışları Python
/// tests/control paketindedir (L009 izolasyon kuralı).
///
/// W6 düzeltmesi: DB adı KOŞUM BAŞINA benzersizdir
/// (``blogdb_b7tests_<epoch-hex>``). Sabit adla iki eşzamanlı ``dotnet test``
/// koşumu aynı DB'ye çarpıp birbirinin bağlantılarını
/// ``DROP ... WITH (FORCE)`` ile kesiyordu (B9 raporu F2). Bayat (2 saatten
/// eski) koşum DB'leri ve sabit adlı eski desen kalıntısı init'te süpürülür.
/// </summary>
public sealed class AgentControlDatabaseFixture : IAsyncLifetime
{
    public const string TestDatabasePrefix = "blogdb_b7tests";

    private string _devConnectionString = string.Empty;
    private string _testConnectionString = string.Empty;

    /// <summary>Bu koşuma özel veritabanı adı (koşum başına benzersiz).</summary>
    public string TestDatabaseName { get; private set; } = string.Empty;

    public string TestConnectionString => _testConnectionString;

    public async Task InitializeAsync()
    {
        _devConnectionString = ResolveDevConnectionString();
        TestDatabaseName = $"{TestDatabasePrefix}_{DateTimeOffset.UtcNow.ToUnixTimeSeconds():x8}";

        var builder = new NpgsqlConnectionStringBuilder(_devConnectionString)
        {
            Database = "postgres",
        };
        await using (var maintenance = new NpgsqlConnection(builder.ConnectionString))
        {
            await maintenance.OpenAsync();
            await SweepStaleRunDatabasesAsync(maintenance);
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

    /// <summary>2 saatten eski koşum DB'lerini süpürür (çökmüş koşumların
    /// bıraktığı kalıntılar); sabit adlı eski desen DB'si koşum bilgisi taşımadığından
    /// her süpürmede düşürülür. Güncel koşumların DB'lerine dokunmaz — eşzamanlı
    /// koşum güvenli.</summary>
    private static async Task SweepStaleRunDatabasesAsync(NpgsqlConnection maintenance)
    {
        var cutoffEpoch = DateTimeOffset.UtcNow.AddHours(-2).ToUnixTimeSeconds();
        var names = new List<string>();
        await using (var cmd = maintenance.CreateCommand())
        {
            cmd.CommandText =
                $"SELECT datname FROM pg_database WHERE datname = '{TestDatabasePrefix}' " +
                $"OR datname LIKE '{TestDatabasePrefix}\\_%' ESCAPE '\\'";
            await using var reader = await cmd.ExecuteReaderAsync();
            while (await reader.ReadAsync())
            {
                names.Add(reader.GetString(0));
            }
        }

        foreach (var name in names)
        {
            if (name != TestDatabasePrefix)
            {
                var suffix = name[(TestDatabasePrefix.Length + 1)..];
                if (!long.TryParse(suffix, System.Globalization.NumberStyles.HexNumber, null, out var epoch)
                    || epoch >= cutoffEpoch)
                {
                    continue; // çözümlenemeyen ad veya güncel koşum: dokunulmaz
                }
            }

            await ExecuteAsync(maintenance,
                $"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{name}' AND pid <> pg_backend_pid()");
            await ExecuteAsync(maintenance, $"DROP DATABASE IF EXISTS \"{name}\" WITH (FORCE)");
        }
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
