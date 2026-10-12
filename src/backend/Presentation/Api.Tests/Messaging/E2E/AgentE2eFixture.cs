using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Presentation.Api.Tests.Messaging.Broker;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Npgsql;
using RabbitMQ.Client;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.E2E;

/// <summary>
/// B11 bileşik uçtan uca (E2E) test ortamı — L009 izolasyon kuralı:
/// broker üzerinde ÖZEL vhost <c>blogapp_w7_b11net</c> (python e2e vhost'u
/// blogapp_w7_b11 ile ÇAKIŞMAZ) ve postgres üzerinde KOŞUM BAŞINA benzersiz
/// scratch DB (blogdb_b11e2e_&lt;epoch-hex&gt;; B5/B9 deseni — sabit adlı iki
/// koşum birbirinin bağlantısını kesmesin).
///
/// Bu ortam tek bir koşumda TAM kabloyu kullanır: gerçek AcceptAgentRunCommand
/// (DB outbox) → gerçek OutboxRelay (confirm'lu yayın) → gerçek broker →
/// kablodan komut doğrulaması (B1 sözleşmesi; python intake'in dayattığı
/// doğrulama) → agent_svc rolüyle olay yayını (python AgentEventPublisher'ın
/// kablo sözleşmesi) → gerçek AgentEventProjectionConsumer → GET run/replay
/// sorguları. Model yolu test sağlayıcısı DEĞİL kablo taklidiyle temsil edilir
/// (gerçek LLM yok — rapor sınırlamaları); bu yüzden suite "worker graph'ı"
/// içermez, onun KABLO KARŞILIĞINI doğrular.
/// </summary>
public sealed class AgentE2eFixture : IAsyncLifetime
{
    public const string TestDatabasePrefix = "blogdb_b11e2e";
    public const string TestVirtualHost = "blogapp_w7_b11net";

    /// <summary>Bu koşuma özel veritabanı adı (koşum başına benzersiz).</summary>
    public string TestDatabaseName { get; private set; } = string.Empty;

    /// <summary>Relay'in dolduğu komut kuyruğu + projection'ın tükettiği olay kuyruğu
    /// (+DLQ'lar); her test öncesi boşaltılır.</summary>
    public static readonly string[] PurgeTargets =
    [
        AgentMessagingTopology.ExecuteQueue,
        AgentMessagingTopology.DeadLetterQueueFor(AgentMessagingTopology.ExecuteQueue),
        AgentMessagingTopology.BackendEventsQueue,
        AgentMessagingTopology.DeadLetterQueueFor(AgentMessagingTopology.BackendEventsQueue),
    ];

    private string _devConnectionString = string.Empty;
    private string _testConnectionString = string.Empty;

    public string TestConnectionString => _testConnectionString;

    /// <summary>backend_svc rolü ayarları (B11 vhost'u; declarer ayrı kimliktir).</summary>
    public RabbitMqSettings BackendSettings() => Copy(BrokerTestEnvironment.BackendSettings(), s =>
    {
        s.VirtualHost = TestVirtualHost;
        s.ClientProvidedName = "backend-net-b11-e2e";
    });

    /// <summary>agent_svc rolü ayarları (olay yayınını gerçek üretici rolüyle kurar).</summary>
    public RabbitMqSettings AgentSettings(string clientName = "agent-py-b11-e2e") => new()
    {
        Host = BrokerTestEnvironment.Host,
        Port = BrokerTestEnvironment.Port,
        UserName = "agent_svc",
        Password = "agent_svc_dev",
        VirtualHost = TestVirtualHost,
        ClientProvidedName = clientName,
    };

    /// <summary>Admin (declarer) ayarları — kablo doğrulama/purge bağlantıları bu
    /// vhost'u kullanır (varsayılan blogapp_dev DEĞİL; L009 izolasyonu).</summary>
    public RabbitMqSettings AdminSettings(string clientName = "b11-e2e-admin") => new()
    {
        Host = BrokerTestEnvironment.Host,
        Port = BrokerTestEnvironment.Port,
        UserName = BrokerTestEnvironment.AdminUser.User,
        Password = BrokerTestEnvironment.AdminUser.Password,
        VirtualHost = TestVirtualHost,
        ClientProvidedName = clientName,
        NetworkRecoveryIntervalSeconds = 2,
    };

    /// <summary>Fixture vhost'unda yönetim amaçlı kısa ömürlü bağlantı açar.</summary>
    public async Task<IConnection> OpenAdminConnectionAsync(
        CancellationToken cancellationToken = default,
        string clientName = "b11-e2e-admin")
    {
        var connection = BrokerTestEnvironment.FactoryFor(AdminSettings(clientName))
            .CreateConnectionAsync(cancellationToken);
        return await connection;
    }

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

    /// <summary>2 saatten eski koşum DB'lerini süpürür (B3/B5 deseni); güncel
    /// koşumların DB'lerine dokunmaz — eşzamanlı koşum güvenli.</summary>
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

    /// <summary>Sınıflar arası yalıtım: E2E tabloları temizlenir.</summary>
    public async Task ResetAsync()
    {
        await using var context = CreateContext();
        await context.Database.ExecuteSqlRawAsync(
            "TRUNCATE agent_event_inbox, outbox_messages, agent_runs, posts, users RESTART IDENTITY CASCADE");
    }

    public async Task<Core.Domain.Entities.User> SeedUserAsync(string userName)
    {
        await using var context = CreateContext();
        var user = new Core.Domain.Entities.User
        {
            UserName = userName,
            Email = $"{userName}@example.com",
            PasswordHash = "test-only-not-a-secret",
        };
        context.Users.Add(user);
        await context.SaveChangesAsync();
        return user;
    }

    public async Task<Core.Domain.Entities.BlogPost> SeedPublishedPostAsync(Guid authorId, string title)
    {
        await using var context = CreateContext();
        var post = new Core.Domain.Entities.BlogPost
        {
            Title = title,
            Slug = $"{title.ToLowerInvariant().Replace(' ', '-')}-{Guid.NewGuid().ToString("N")[..8]}",
            Content = $"# {title}\n\nB11 E2E makale içeriği: agent soruları bu bağlamla sorulur.",
            Status = PostStatus.Published,
            AuthorId = authorId,
            ContentRevision = 1,
        };
        post.Publish();
        context.Posts.Add(post);
        await context.SaveChangesAsync();
        return post;
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
                // PASIF declare: kuyruk declarer tarafından DLX argümanıyla bildirilmiştir.
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

    /// <summary>Yönetim API üzerinden kuyruğun ready/unacked sayaçlarını okur.
    /// Passive declare yalnız READY mesajı sayar; teslim alınıp ACK'lanmamış
    /// (unacked) mesajlar sayımda görünmez — commit→ACK yarışı doğrulaması için
    /// unacked sayımı şart (AMQP protocol: kapanışta unacked mesaj requeue edilir).</summary>
    public async Task<(int Ready, int Unacked)> QueueCountsAsync(string queue)
    {
        using var client = CreateManagementClient();
        var response = await client.GetAsync(
            $"api/queues/{Uri.EscapeDataString(TestVirtualHost)}/{Uri.EscapeDataString(queue)}");
        response.EnsureSuccessStatusCode();
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var root = document.RootElement;
        var ready = root.TryGetProperty("messages_ready", out var readyElement)
            ? readyElement.GetInt32() : 0;
        var unacked = root.TryGetProperty("messages_unacknowledged", out var unackedElement)
            ? unackedElement.GetInt32() : 0;
        return (ready, unacked);
    }

    private async Task ProvisionVirtualHostAsync()
    {
        await WithManagementRetryAsync(async client =>
        {
            var response = await client.PutAsync(
                $"api/vhosts/{Uri.EscapeDataString(TestVirtualHost)}", null);
            response.EnsureSuccessStatusCode();

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

            // D013 izin modeli (B2/B5 provizyonu ile birebir):
            // backend_svc — declarer (configure .*) + commands/content write; agent_svc —
            // yalnız events write + kendi kuyruklarını okuma.
            await PutPermissionAsync(client,
                ".*",
                @"blog\.(agent\.commands|content\.events)",
                @"backend\.agent\.events\.q(\.dlq)?|agent\.(execute|control|content)\.q",
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
            catch (HttpRequestException exception)
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
        await initializer.InitializeAsync();
    }

    private static HttpClient CreateManagementClient()
    {
        var client = new HttpClient
        {
            BaseAddress = new Uri("http://127.0.0.1:15672/"),
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

/// <summary>B11 E2E koleksiyonu: fixture'ı paylaşan testler SIRALI koşar
/// (xunit.runner.json serileri — L009).</summary>
[CollectionDefinition("agent-e2e-b11")]
public sealed class AgentE2eCollection : ICollectionFixture<AgentE2eFixture>
{
}
