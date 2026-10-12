using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Presentation.Api.Tests.Messaging.Broker;
using RabbitMQ.Client;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Content;

/// <summary>
/// B8 broker test ortamı (L009): ÖZEL vhost ``blogapp_dev_b8net`` — B2 (blogapp_dev)
/// ve Python B8 testlerinin (blogapp_dev_b8) kuyruklarıyla paylaşımlı çalışmaz.
/// Management API ile idempotent provizyon; declarer blogapp admin kimliğidir (K3/D013).
/// </summary>
internal static class ContentBrokerEnvironment
{
    internal static string ManagementUrl =>
        Environment.GetEnvironmentVariable("RABBITMQ_MGMT_URL") ?? "http://127.0.0.1:15672/api";

    internal static string VirtualHost =>
        Environment.GetEnvironmentVariable("RABBITMQ_VHOST_B8NET") ?? "blogapp_dev_b8net";

    internal static (string User, string Password) AdminUser =>
        (Environment.GetEnvironmentVariable("RABBITMQ_ADMIN_USER") ?? "blogapp",
         Environment.GetEnvironmentVariable("RABBITMQ_ADMIN_PASSWORD") ?? "blogapp_dev");

    internal static (string User, string Password) BackendUser =>
        (Environment.GetEnvironmentVariable("RABBITMQ_BACKEND_USER") ?? "backend_svc",
         Environment.GetEnvironmentVariable("RABBITMQ_BACKEND_PASSWORD") ?? "backend_svc_dev");

    internal static RabbitMqSettings BackendSettings() => new()
    {
        Host = BrokerTestEnvironment.Host,
        Port = BrokerTestEnvironment.Port,
        UserName = BackendUser.User,
        Password = BackendUser.Password,
        VirtualHost = VirtualHost,
        ClientProvidedName = "backend-net-b8-tests",
        RequestedHeartbeatSeconds = 30,
        NetworkRecoveryIntervalSeconds = 2,
        DeclarerUserName = AdminUser.User,
        DeclarerPassword = AdminUser.Password,
    };

    internal static async Task ProvisionAsync()
    {
        using var client = new HttpClient();
        var token = Convert.ToBase64String(Encoding.UTF8.GetBytes($"{AdminUser.User}:{AdminUser.Password}"));
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Basic", token);

        var vhost = Uri.EscapeDataString(VirtualHost);
        var response = await client.PutAsync($"{ManagementUrl}/vhosts/{vhost}", content: null);
        Assert.True(response.IsSuccessStatusCode || (int)response.StatusCode == 204,
            $"vhost provizyonu başarısız: {(int)response.StatusCode}");

        await PutPermission(client, vhost, AdminUser.User, ".*", ".*", ".*");
        // Backend rolü (K3): komut+content exchange'lerine yazar; kuyruk kaynağına read
        // (DLX'li kuyruk yaratımı declarer'dan read ister — RabbitMQ 4.2 ölçümü, B2 raporu).
        await PutPermission(client, vhost, BackendUser.User,
            configure: ".*",
            write: @"blog\.(agent\.commands|content\.events)",
            read: @"agent\.(execute|control|content)\.q(\.dlq)?|backend\.agent\.events\.q(\.dlq)?");
    }

    private static async Task PutPermission(
        HttpClient client, string vhost, string user, string configure, string write, string read)
    {
        var response = await client.PutAsJsonAsync(
            $"{ManagementUrl}/permissions/{vhost}/{Uri.EscapeDataString(user)}",
            new { configure, write, read });
        Assert.True(response.IsSuccessStatusCode || (int)response.StatusCode == 201 || (int)response.StatusCode == 204,
            $"izin provizyonu başarısız: {user} -> {(int)response.StatusCode}");
    }
}

/// <summary>
/// B8 gerçek broker testleri: AgentContentEventService'in yazdığı ArticleContentChangedV1
/// zarfı gerçek blog.content.events exchange'ine routing edilir ve B1 sözleşme doğrulayıcısından
/// geçer. Outbox→relay transport zincirinin kendisi B3'te kanıtlanmıştır; burada içerik olayının
/// exchange/routing/payload hattı kanıtlanır (relay türden bağımsızdır).
/// </summary>
[Collection("agent-content-sync-b8")]
public class ContentEnvelopeBrokerTests : IAsyncLifetime
{
    public async Task InitializeAsync()
    {
        await ContentBrokerEnvironment.ProvisionAsync();

        // Relay'in passive declare'ına dayanmadan önce topology idempotent kurulur.
        await using var initializer = new AgentTopologyInitializer(ContentBrokerEnvironment.BackendSettings());
        await initializer.InitializeAsync(new CancellationTokenSource(TimeSpan.FromMinutes(2)).Token);
    }

    public Task DisposeAsync() => Task.CompletedTask;

    [Fact]
    public async Task ArticleChangedEnvelope_RoutesToContentExchangeAndValidates()
    {
        var settings = ContentBrokerEnvironment.BackendSettings();
        var envelopeJson = AgentContentEventComposer.ComposeArticleChanged(
            articleId: Guid.NewGuid(),
            articleRevision: 3,
            action: AgentContentEventService.ActionUpdated,
            contentHash: AgentContentEventComposer.ComputeContentHash("# Broker\n\nTest."),
            language: null,
            title: "Broker Test",
            producer: "backend-net");

        // Scratch kuyruk: content exchange'e rk ile bağlı; admin (declarer) bağlantısıyla kurulur.
        var scratchQueue = $"b8net-scratch-{Guid.NewGuid():N}";
        var factory = BrokerTestEnvironment.FactoryFor(new RabbitMqSettings
        {
            Host = BrokerTestEnvironment.Host,
            Port = BrokerTestEnvironment.Port,
            UserName = ContentBrokerEnvironment.AdminUser.User,
            Password = ContentBrokerEnvironment.AdminUser.Password,
            VirtualHost = ContentBrokerEnvironment.VirtualHost,
            ClientProvidedName = "b8net-admin-scratch",
        });

        var connection = await factory.CreateConnectionAsync();
        await using (connection)
        {
            var channel = await connection.CreateChannelAsync();
            await using (channel)
            {
                await channel.QueueDeclareAsync(scratchQueue, durable: false, exclusive: true, autoDelete: true);
                await channel.QueueBindAsync(scratchQueue, AgentMessageTypeRegistry.ContentExchange, "content.article.changed.v1");

                await using var connections = new RabbitMqConnectionManager(settings);
                await using var publisher = new RabbitMqAgentPublisher(
                    connections, settings, [AgentMessageTypeRegistry.ContentExchange]);
                await publisher.StartAsync();
                var result = await publisher.PublishAsync(
                    AgentMessageTypeRegistry.ContentExchange,
                    "content.article.changed.v1",
                    Encoding.UTF8.GetBytes(envelopeJson.EnvelopeJson),
                    messageId: envelopeJson.MessageId,
                    type: AgentMessageTypes.ArticleContentChanged);
                Assert.True(result.Confirmed, result.Detail);

                var received = await channel.BasicGetAsync(scratchQueue, autoAck: true);
                Assert.NotNull(received); // unroutable düşme yok: binding çalışıyor
                Assert.Equal("content.article.changed.v1", received!.RoutingKey);
                Assert.Equal(envelopeJson.MessageId, received.BasicProperties.MessageId);

                var bodyText = Encoding.UTF8.GetString(received.Body.ToArray());
                var validation = new AgentContractValidator().Validate(bodyText);
                Assert.True(validation.IsValid, validation.Error?.Message);

                var payload = JsonDocument.Parse(bodyText).RootElement.GetProperty("payload").Clone();
                Assert.Equal("updated", payload.GetProperty("action").GetString());
                Assert.Equal(3, payload.GetProperty("article_revision").GetInt64());
            }
        }
    }
}
