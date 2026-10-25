using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Presentation.Api.Tests.Messaging.Broker;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using Npgsql;
using RabbitMQ.Client;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Projection;

/// <summary>
/// B5 test ortamı: docker compose postgres üzerinde İZOLE test veritabanı +
/// broker üzerinde ÖZEL vhost (blogapp_dev_b5net) — B2/B3 (blogapp_dev) ve
/// B4/B5-python (blogapp_dev_b4/b5) paketleriyle kuyruk paylaşımı yok; paralel
/// purge/drain karışması engellenir.
///
/// W6 düzeltmesi: DB adı KOŞUM BAŞINA benzersizdir
/// (``blogdb_b5tests_<epoch-hex>``). Sabit adla iki eşzamanlı ``dotnet test``
/// koşumu aynı DB'ye çarpıp birbirinin bağlantılarını
/// ``DROP ... WITH (FORCE)`` ile kesiyordu (B9 raporu F2). Bayat (2 saatten
/// eski) koşum DB'leri ve sabit adlı eski desen kalıntısı init'te süpürülür.
/// Değerler ortam değişkeniyle override edilebilir; parolalar log'a yazılmaz.
/// </summary>
public sealed class AgentEventProjectionFixture : IAsyncLifetime
{
    public const string TestDatabasePrefix = "blogdb_b5tests";
    public const string TestVirtualHost = "blogapp_dev_b5net";

    /// <summary>Bu koşuma özel veritabanı adı (koşum başına benzersiz).</summary>
    public string TestDatabaseName { get; private set; } = string.Empty;

    public static readonly string[] PurgeTargets =
    [
        AgentMessagingTopology.BackendEventsQueue,
        AgentMessagingTopology.DeadLetterQueueFor(AgentMessagingTopology.BackendEventsQueue)
    ];

    private string _devConnectionString = string.Empty;
    private string _testConnectionString = string.Empty;

    public string TestConnectionString => _testConnectionString;

    /// <summary>backend_svc rolü ayarları (B5 vhost'u; declarer ayrı kimliktir).</summary>
    public RabbitMqSettings BackendSettings() => Copy(BrokerTestEnvironment.BackendSettings(), s =>
    {
        s.VirtualHost = TestVirtualHost;
        s.ClientProvidedName = "backend-net-b5-tests";
    });

    /// <summary>agent_svc rolü ayarları (olay yayınını gerçek üretici rolüyle kurar).</summary>
    public RabbitMqSettings AgentSettings() => new()
    {
        Host = BrokerTestEnvironment.Host,
        Port = BrokerTestEnvironment.Port,
        UserName = "agent_svc",
        Password = "agent_svc_dev",
        VirtualHost = TestVirtualHost,
        ClientProvidedName = "agent-py-b5-tests",
    };

    private static RabbitMqSettings Copy(RabbitMqSettings source, Action<RabbitMqSettings> mutate)
    {
        var copy = new RabbitMqSettings
        {
            Host = source.Host,
            Port = source.Port,
            UserName = source.UserName,
            Password = source.Password,
            VirtualHost = source.VirtualHost,
            ClientProvidedName = source.ClientProvidedName,
            RequestedHeartbeatSeconds = source.RequestedHeartbeatSeconds,
            NetworkRecoveryIntervalSeconds = source.NetworkRecoveryIntervalSeconds,
            ConsumerPrefetchCount = source.ConsumerPrefetchCount,
            MaxPublishBytes = source.MaxPublishBytes,
            DeclarerUserName = source.DeclarerUserName,
            DeclarerPassword = source.DeclarerPassword,
        };
        mutate(copy);
        return copy;
    }

    public async Task InitializeAsync()
    {
        _devConnectionString = ResolveDevConnectionString();
        TestDatabaseName = $"{TestDatabasePrefix}_{DateTimeOffset.UtcNow.ToUnixTimeSeconds():x8}";

        var maintenanceBuilder = new NpgsqlConnectionStringBuilder(_devConnectionString)
        {
            Database = "postgres",
        };
        await using (var maintenance = new NpgsqlConnection(maintenanceBuilder.ConnectionString))
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

        await using (var context = CreateContext())
        {
            await context.Database.MigrateAsync();
        }

        await ProvisionVirtualHostAsync();
        await DeclareTopologyAsync();
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
        // canlı Npgsql havuzuyla yarışmasın.
        NpgsqlConnection.ClearAllPools();

        var builder = new NpgsqlConnectionStringBuilder(_devConnectionString)
        {
            Database = "postgres",
        };
        await using var maintenance = new NpgsqlConnection(builder.ConnectionString);
        await maintenance.OpenAsync();
        await ExecuteAsync(maintenance,
            $"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{TestDatabaseName}' AND pid <> pg_backend_pid()");

        // DROP, backend sonlanmasının yayılmasıyla yarışabilir: sınırlı,
        // artan beklemeli tekrar.
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

    /// <summary>Sınıflar arası yalıtım: B5 tabloları temizlenir.</summary>
    public async Task ResetAsync()
    {
        await using var context = CreateContext();
        await context.Database.ExecuteSqlRawAsync(
            "TRUNCATE agent_event_inbox, agent_runs RESTART IDENTITY CASCADE");
    }

    public async Task PurgeQueuesAsync()
    {
        var factory = BrokerTestEnvironment.FactoryFor(BackendSettings());
        await using var connection = await factory.CreateConnectionAsync();
        await using var channel = await connection.CreateChannelAsync();
        foreach (var queue in PurgeTargets)
        {
            try
            {
                // PASIF declare: kuyruk declarer (AgentTopologyInitializer) tarafından
                // DLX argümanıyla bildirilmiştir; argümansız aktif declare
                // PRECONDITION_FAILED üretir.
                await channel.QueueDeclareAsync(queue, durable: true, exclusive: false,
                    autoDelete: false, arguments: null, passive: true);
                await channel.QueuePurgeAsync(queue);
            }
            catch (RabbitMQ.Client.Exceptions.OperationInterruptedException)
            {
                // kuyruk henüz yok: purge edilecek bir şey de yok
            }
        }
    }

    public async Task<int> QueueDepthAsync(string queue)
    {
        var factory = BrokerTestEnvironment.FactoryFor(BackendSettings());
        await using var connection = await factory.CreateConnectionAsync();
        await using var channel = await connection.CreateChannelAsync();
        var declared = await channel.QueueDeclareAsync(queue, durable: true, exclusive: false,
            autoDelete: false, arguments: null, passive: true);
        return (int)declared.MessageCount;
    }

    private async Task ProvisionVirtualHostAsync()
    {
        // Yüklü brokerda management HTTP bağlantıları kopabilir (python conftest'te
        // gözlemlenen davranış): sınırlı, artan backoff'lu retry uygulanır.
        await WithManagementRetryAsync(async client =>
        {
            var response = await client.PutAsync(
                $"api/vhosts/{Uri.EscapeDataString(TestVirtualHost)}", null);
            response.EnsureSuccessStatusCode();

            // A management administrator still needs explicit AMQP permission
            // on a newly created test vhost. Application roles remain bounded.
            await PutPermissionAsync(client, ".*", ".*", ".*", BrokerTestEnvironment.AdminUser.User);

            foreach (var (user, password) in new[]
                     {
                         BrokerTestEnvironment.BackendUser,
                         ("agent_svc", "agent_svc_dev")
                     })
            {
                var userResponse = await client.PutAsync(
                    $"api/users/{Uri.EscapeDataString(user)}",
                    JsonContent.Create(new { password, tags = "none" }));
                userResponse.EnsureSuccessStatusCode();
            }

            await PutPermissionAsync(client,
                ".*", // configure
                @"blog\.(agent\.commands|content\.events)", // write
                @"backend\.agent\.events\.q(\.dlq)?|agent\.(execute|control|content)\.q", // read
                BrokerTestEnvironment.BackendUser.User);
            await PutPermissionAsync(client,
                "",
                @"blog\.agent\.events",
                @"agent\.(execute|control|content)\.q(\.dlq)?",
                "agent_svc");
        });
    }

    private static async Task WithManagementRetryAsync(Func<HttpClient, Task> action, int attempts = 5)
    {
        Exception? lastError = null;
        for (var attempt = 0; attempt < attempts; attempt++)
        {
            try
            {
                using var client = CreateManagementClient();
                await action(client);
                return;
            }
            catch (HttpRequestException exception) when (exception.StatusCode is null || (int)exception.StatusCode.Value >= 500)
            {
                lastError = exception;
                await Task.Delay(TimeSpan.FromMilliseconds(500 * Math.Pow(2, attempt)));
            }
            catch (TaskCanceledException exception) when (exception.InnerException is TimeoutException)
            {
                lastError = exception;
                await Task.Delay(TimeSpan.FromMilliseconds(500 * Math.Pow(2, attempt)));
            }
        }
        throw new InvalidOperationException("management provisioning başarısız", lastError);
    }

    private async Task PutPermissionAsync(
        HttpClient client, string configure, string write, string read, string user)
    {
        var body = JsonContent.Create(new { configure, write, read });
        var response = await client.PutAsync(
            $"api/permissions/{Uri.EscapeDataString(TestVirtualHost)}/{Uri.EscapeDataString(user)}", body);
        response.EnsureSuccessStatusCode();
    }

    private async Task DeclareTopologyAsync()
    {
        var settings = BackendSettings();
        settings.DeclarerUserName = BrokerTestEnvironment.AdminUser.User;
        settings.DeclarerPassword = BrokerTestEnvironment.AdminUser.Password;
        await using var initializer = new AgentTopologyInitializer(settings);
        using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(2));
        await initializer.InitializeAsync(timeout.Token);
    }

    private static HttpClient CreateManagementClient()
    {
        var client = new HttpClient
        {
            BaseAddress = BrokerTestEnvironment.ManagementBaseAddress,
            Timeout = TimeSpan.FromSeconds(10),
        };
        var token = Convert.ToBase64String(Encoding.UTF8.GetBytes(
            $"{BrokerTestEnvironment.AdminUser.User}:{BrokerTestEnvironment.AdminUser.Password}"));
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Basic", token);
        return client;
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
                "appsettings.Development.json ConnectionStrings:DefaultConnection okunamadı.");
        }

        return connectionString;
    }
}

/// <summary>B5 test koleksiyonu: postgres + broker vhost fixture'ı paylaşılır.</summary>
[CollectionDefinition("agent-event-projection")]
public sealed class AgentEventProjectionCollection : ICollectionFixture<AgentEventProjectionFixture>
{
}

/// <summary>AgentRun kabul kaydı seed aracı (projection hedefi).</summary>
public static class AgentRunSeeder
{
    public static async Task<AgentRun> SeedAsync(
        AppDbContext context, Guid? runId = null, string ownerKey = "u:b5-test-user")
    {
        var run = new AgentRun
        {
            Id = runId ?? Guid.NewGuid(),
            ConversationId = Guid.NewGuid(),
            TurnSequence = 1,
            OwnerKey = ownerKey,
            IdempotencyKey = $"idem-{Guid.NewGuid():N}",
            IdempotencyPayloadHash = new string('a', 64),
            Status = AgentRunStatus.Accepted,
            Question = "B5 test sorusu",
            Language = "tr",
            ModePreference = "auto",
            BudgetProfile = "default",
            ContextSnapshotReference = $"agent-run/{runId}/turn/1",
            ContextSnapshotJson = """{"question":"B5 test sorusu"}""",
            DeadlineAt = DateTime.UtcNow.AddMinutes(10),
            AcceptedAt = DateTime.UtcNow,
        };
        context.AgentRuns.Add(run);
        await context.SaveChangesAsync();
        return run;
    }
}

/// <summary>Test için bildirim kaydeden notifier (IAgentRunNotifier takısı).</summary>
public sealed class RecordingNotifier : IAgentRunNotifier
{
    private readonly object _gate = new();

    public List<AgentRunNotification> Notifications { get; } = [];

    public int Count
    {
        get { lock (_gate) { return Notifications.Count; } }
    }

    public Task NotifyAsync(AgentRunNotification notification, CancellationToken cancellationToken = default)
    {
        lock (_gate)
        {
            Notifications.Add(notification);
        }
        return Task.CompletedTask;
    }
}

/// <summary>Test tanısında consumer/handler loglarını tutan hafıza sağlayıcı.</summary>
public sealed class MemoryLogProvider : ILoggerProvider
{
    private readonly object _gate = new();

    public List<string> Entries { get; } = [];

    public ILogger CreateLogger(string categoryName) => new MemoryLogger(this, categoryName);

    private sealed class MemoryLogger(MemoryLogProvider owner, string category) : ILogger
    {
        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => logLevel >= LogLevel.Information;

        public void Log<TState>(
            LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
        {
            if (!IsEnabled(logLevel))
            {
                return;
            }
            lock (owner._gate)
            {
                owner.Entries.Add($"[{logLevel}] {category}: {formatter(state, exception)}{(exception is null ? "" : $" :: {exception.GetType().Name}: {exception.Message}")}");
            }
        }
    }

    public void Dispose()
    {
    }
}
