using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Messaging;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentInternalContentQuery;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Messaging;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Infrastructure.Persistence.Repositories;
using BlogApp.Presentation.Api.Endpoints;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Agent;

/// <summary>
/// Agent internal content ucu (B12 sabit sözleşme) gövde testi: GERÇEK HTTP +
/// GERÇEK Postgres üstünde GET /api/v1/agent/internal/content/{articleId}
/// davranışı doğrulanır — servis anahtarı yetkisi (sabit zamanlı karşılaştırma),
/// yüzey sızdırma (anahtar yapılandırılmamışsa 404), Published filtresi ve
/// contentHash'in kabul anındaki AgentRun.ArticleContentHash ile BİREBİR aynı
/// fonksiyondan (AgentArticleContentHash) üretildiği iddiası. Broker gerektirmez.
/// </summary>
[Collection("agent-b10")]
public class AgentInternalContentEndpointTests : IAsyncLifetime
{
    private const string ServiceKey = "test-agent-internal-service-key";

    private readonly AgentB10DatabaseFixture _fixture;

    public AgentInternalContentEndpointTests(AgentB10DatabaseFixture fixture) => _fixture = fixture;

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    [Fact]
    public async Task Get_WithValidKey_Returns200WithContractBody()
    {
        var (article, content) = await SeedPublishedArticleAsync(contentRevision: 7);

        var cancellationToken = NewTestToken();
        await using var app = BuildHost(ServiceKey);
        await app.StartAsync(cancellationToken);
        using var client = new HttpClient { BaseAddress = new Uri(app.Urls.First()) };
        client.DefaultRequestHeaders.Add(AgentInternalEndpoints.ServiceKeyHeaderName, ServiceKey);

        using var response = await client.GetAsync(
            $"/api/v1/agent/internal/content/{article.Id:D}",
            cancellationToken);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellationToken));
        var root = document.RootElement;
        Assert.True(root.GetProperty("success").GetBoolean());

        var data = root.GetProperty("data");
        Assert.Equal(article.Id.ToString("D"), data.GetProperty("articleId").GetString());
        Assert.Equal(7, data.GetProperty("revision").GetInt64());
        Assert.Equal(article.Title, data.GetProperty("title").GetString());
        Assert.Equal(content, data.GetProperty("content").GetString());
        Assert.Equal(2, data.GetProperty("tags").GetArrayLength());
        Assert.Contains("dotnet", data.GetProperty("tags").EnumerateArray().Select(t => t.GetString()));
        Assert.Contains("agent", data.GetProperty("tags").EnumerateArray().Select(t => t.GetString()));
        // publishedAt ISO 8601'dir ve parse edilir.
        Assert.True(DateTimeOffset.TryParse(data.GetProperty("publishedAt").GetString(), out _));

        // contentHash: kabul anındaki ArticleContentHash ALGORİTMASININ çıktısı
        // (UTF-8 SHA-256, lowercase hex) — test tarafında aynı ifadeyle üretilir.
        Assert.Equal(Sha256HexLower(content), data.GetProperty("contentHash").GetString());
    }

    [Fact]
    public async Task Get_WithoutKey_Returns401()
    {
        var (article, _) = await SeedPublishedArticleAsync();

        var cancellationToken = NewTestToken();
        await using var app = BuildHost(ServiceKey);
        await app.StartAsync(cancellationToken);
        using var client = new HttpClient { BaseAddress = new Uri(app.Urls.First()) };

        using var response = await client.GetAsync(
            $"/api/v1/agent/internal/content/{article.Id:D}",
            cancellationToken);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Get_WithWrongKey_Returns401()
    {
        var (article, _) = await SeedPublishedArticleAsync();

        var cancellationToken = NewTestToken();
        await using var app = BuildHost(ServiceKey);
        await app.StartAsync(cancellationToken);
        using var client = new HttpClient { BaseAddress = new Uri(app.Urls.First()) };
        client.DefaultRequestHeaders.Add(AgentInternalEndpoints.ServiceKeyHeaderName, "wrong-key");

        using var response = await client.GetAsync(
            $"/api/v1/agent/internal/content/{article.Id:D}",
            cancellationToken);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Get_WhenKeyNotConfigured_Returns404EvenWithKey()
    {
        // Yüzey sızdırma: anahtar yapılandırılmamışsa uç HER istek için 404 döner —
        // anahtarı bilen bile endpoint'in varlığını öğrenemez.
        var (article, _) = await SeedPublishedArticleAsync();

        var cancellationToken = NewTestToken();
        await using var app = BuildHost(internalApiKey: null);
        await app.StartAsync(cancellationToken);
        using var client = new HttpClient { BaseAddress = new Uri(app.Urls.First()) };
        client.DefaultRequestHeaders.Add(AgentInternalEndpoints.ServiceKeyHeaderName, ServiceKey);

        using var response = await client.GetAsync(
            $"/api/v1/agent/internal/content/{article.Id:D}",
            cancellationToken);

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task Get_DraftArticle_Returns404()
    {
        var (article, _) = await SeedPublishedArticleAsync(status: PostStatus.Draft);

        var cancellationToken = NewTestToken();
        await using var app = BuildHost(ServiceKey);
        await app.StartAsync(cancellationToken);
        using var client = new HttpClient { BaseAddress = new Uri(app.Urls.First()) };
        client.DefaultRequestHeaders.Add(AgentInternalEndpoints.ServiceKeyHeaderName, ServiceKey);

        using var response = await client.GetAsync(
            $"/api/v1/agent/internal/content/{article.Id:D}",
            cancellationToken);

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task Get_MissingArticle_Returns404()
    {
        var cancellationToken = NewTestToken();
        await using var app = BuildHost(ServiceKey);
        await app.StartAsync(cancellationToken);
        using var client = new HttpClient { BaseAddress = new Uri(app.Urls.First()) };
        client.DefaultRequestHeaders.Add(AgentInternalEndpoints.ServiceKeyHeaderName, ServiceKey);

        using var response = await client.GetAsync(
            $"/api/v1/agent/internal/content/{Guid.NewGuid():D}",
            cancellationToken);

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    /// <summary>Hash iddiası (sabit sözleşme): ucu, GERÇEK kabul yolunun
    /// AgentRun.ArticleContentHash'e yazdığı değerle AYNI contentHash'i döndürür.
    /// Kabul gerçek AcceptAgentRunCommandHandler ile koşturulur (mock kabul anı
    /// değil); iki değer de test tarafındaki inline SHA-256 hesabıyla eşlenir.</summary>
    [Fact]
    public async Task Get_ContentHash_MatchesAcceptanceTimeArticleContentHash()
    {
        var (article, content) = await SeedPublishedArticleAsync(contentRevision: 3);

        // 1) GERÇEK kabul: AgentRun.ArticleContentHash kabul anında yazılır.
        var acceptanceToken = NewTestToken();
        Guid runId;
        await using (var app = BuildAcceptanceHost(userId: Guid.NewGuid()))
        {
            await app.StartAsync(acceptanceToken);
            var mediator = app.Services.GetRequiredService<MediatR.IMediator>();
            var result = await mediator.Send(new AcceptAgentRunCommandRequest
            {
                Question = "Hash parite sorusu",
                Language = "tr",
                ModePreference = "auto",
                ArticleId = article.Id,
                IdempotencyKey = $"idem-{Guid.NewGuid():N}",
            }, acceptanceToken);
            Assert.True(result.IsSuccess, "gerçek kabul başarısız: " + string.Join(", ", result.Errors));
            runId = result.Value!.RunId;
        }

        Guid? acceptanceArticleId;
        string? acceptanceHash;
        await using (var context = _fixture.CreateContext())
        {
            var run = await context.AgentRuns.AsNoTracking().SingleAsync(r => r.Id == runId);
            acceptanceArticleId = run.ArticleId;
            acceptanceHash = run.ArticleContentHash;
        }

        Assert.Equal(article.Id, acceptanceArticleId);
        Assert.Equal(Sha256HexLower(content), acceptanceHash);

        // 2) Internal uç: AYNI makale için AYNI hash.
        var cancellationToken = NewTestToken();
        await using var endpointApp = BuildHost(ServiceKey);
        await endpointApp.StartAsync(cancellationToken);
        using var client = new HttpClient { BaseAddress = new Uri(endpointApp.Urls.First()) };
        client.DefaultRequestHeaders.Add(AgentInternalEndpoints.ServiceKeyHeaderName, ServiceKey);

        using var response = await client.GetAsync(
            $"/api/v1/agent/internal/content/{article.Id:D}",
            cancellationToken);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellationToken));
        var endpointHash = document.RootElement.GetProperty("data").GetProperty("contentHash").GetString();

        Assert.Equal(acceptanceHash, endpointHash);
        Assert.Equal(Sha256HexLower(content), endpointHash);
    }

    // ------------------------------------------------------------- yardımcılar

    private static CancellationToken NewTestToken() =>
        new CancellationTokenSource(TimeSpan.FromSeconds(60)).Token;

    /// <summary>Kabul anındaki ArticleContentHash ifadesi (AcceptAgentRunCommandHandler.
    /// BuildContextSnapshot'ın refactor öncesi birebir hâli; Python
    /// compute_content_hash = sha256(utf-8).hexdigest() ile aynı çıktı).</summary>
    private static string Sha256HexLower(string content) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(content))).ToLowerInvariant();

    private async Task<(BlogPost Article, string Content)> SeedPublishedArticleAsync(
        long contentRevision = 5,
        PostStatus status = PostStatus.Published)
    {
        const string content = "# Internal content testi\n\nB12 sabit sözleşme gövdesi. Markdown içerik.";

        await using var context = _fixture.CreateContext();
        var author = new User
        {
            UserName = $"b12-user-{Guid.NewGuid():N}",
            Email = $"b12-{Guid.NewGuid():N}@example.com",
            PasswordHash = "test-only-not-a-secret",
        };
        context.Users.Add(author);

        var dotnetTag = await context.Tags.FirstOrDefaultAsync(t => t.Name == "dotnet");
        if (dotnetTag is null)
        {
            dotnetTag = new Tag { Name = "dotnet", Slug = $"dotnet-{Guid.NewGuid():N}" };
            context.Tags.Add(dotnetTag);
        }

        var agentTag = await context.Tags.FirstOrDefaultAsync(t => t.Name == "agent");
        if (agentTag is null)
        {
            agentTag = new Tag { Name = "agent", Slug = $"agent-{Guid.NewGuid():N}" };
            context.Tags.Add(agentTag);
        }

        var article = new BlogPost
        {
            Title = "Internal content uç testi makalesi",
            Slug = $"internal-content-test-{Guid.NewGuid():N}",
            Content = content,
            Status = status,
            AuthorId = author.Id,
            ContentRevision = contentRevision,
        };
        if (status == PostStatus.Published)
        {
            article.Publish();
        }

        article.Tags.Add(dotnetTag);
        article.Tags.Add(agentTag);
        context.Posts.Add(article);
        await context.SaveChangesAsync();
        return (article, content);
    }

    /// <summary>Internal content ucunun mini hostu: yalnız endpoint + MediatR +
    /// projection DbContext; servis anahtarı Options.Create ile SABİT verilir
    /// (appsettings yüklemesi kararı belirlemez).</summary>
    private WebApplication BuildHost(string? internalApiKey)
    {
        var builder = WebApplication.CreateBuilder();
        builder.WebHost.UseUrls("http://127.0.0.1:0");

        builder.Services.AddDbContext<AppDbContext>(options => options.UseNpgsql(
            _fixture.TestConnectionString,
            npgsql => npgsql.MigrationsAssembly(typeof(AppDbContext).Assembly.FullName)));
        builder.Services.AddScoped<IApplicationDbContext>(sp => sp.GetRequiredService<AppDbContext>());
        builder.Services.AddMediatR(cfg =>
            cfg.RegisterServicesFromAssembly(typeof(GetAgentInternalContentQueryHandler).Assembly));
        builder.Services.AddSingleton(Options.Create(new AgentServiceSettings
        {
            InternalApiKey = internalApiKey,
        }));

        var app = builder.Build();
        app.RegisterAgentInternalEndpoints();
        return app;
    }

    /// <summary>Gerçek kabul yolunun hostu: AcceptAgentRunCommandHandler'ın tüm
    /// bağımlılıkları üretim sınıflarıyla kurulur (UnitOfWork, EfOutboxWriter,
    /// ayarlar) — hash iddiası mock kabulle DEĞİL gerçek handler ile kanıtlanır.</summary>
    private WebApplication BuildAcceptanceHost(Guid userId)
    {
        var builder = WebApplication.CreateBuilder();
        builder.WebHost.UseUrls("http://127.0.0.1:0");

        builder.Services.AddDbContext<AppDbContext>(options => options.UseNpgsql(
            _fixture.TestConnectionString,
            npgsql => npgsql.MigrationsAssembly(typeof(AppDbContext).Assembly.FullName)));
        builder.Services.AddScoped<IApplicationDbContext>(sp => sp.GetRequiredService<AppDbContext>());
        builder.Services.AddScoped<IUnitOfWork>(sp => new UnitOfWork(sp.GetRequiredService<AppDbContext>()));
        builder.Services.AddScoped<IOutboxWriter>(sp => new EfOutboxWriter(sp.GetRequiredService<AppDbContext>()));
        builder.Services.AddSingleton<ICurrentUserService>(new TestCurrentUser(userId));
        builder.Services.AddSingleton(Options.Create(new AgentAcceptanceSettings()));
        builder.Services.AddSingleton(Options.Create(new AgentMessagingSettings()));
        builder.Services.AddSingleton(typeof(Microsoft.Extensions.Logging.ILogger<>), typeof(NullLogger<>));
        builder.Services.AddMediatR(cfg =>
            cfg.RegisterServicesFromAssembly(typeof(AcceptAgentRunCommandHandler).Assembly));

        var app = builder.Build();
        return app;
    }
}
