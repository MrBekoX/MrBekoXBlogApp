using System.Net;
using System.Text;
using System.Text.Json;
using Asp.Versioning;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunEventsQuery;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Persistence;
using BlogApp.Presentation.Api.Endpoints;
using BlogApp.Presentation.Api.Services;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Agent;

/// <summary>
/// Agent live-steps SSE gövde testi (ADDITIVE): GET /runs/{runId}/events'in
/// ``text/event-stream`` dalı (AgentEndpoints.StreamEventsAsync) GERÇEK HTTP
/// üstünde koşulur ve JSON replay ile AYNI ortak olay yüzeyi alanlarını
/// (kind/message/detail) taşıdığı doğrulanır. Broker gerektirmez: mini
/// WebApplication yalnız endpoint + MediatR + projection DbContext kaydeder;
/// kimlik sabit ICurrentUserService test çiftinden gelir (B10 deseni).
/// </summary>
[Collection("agent-b10")]
public class AgentRunEventsSseSurfaceTests : IAsyncLifetime
{
    private readonly AgentB10DatabaseFixture _fixture;

    public AgentRunEventsSseSurfaceTests(AgentB10DatabaseFixture fixture) => _fixture = fixture;

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    /// <summary>SSE akışı terminal run'da hemen "done" ile kapanır; 60 sn üst sınır
    /// beklenmedik takılmada testi sonlandırır.</summary>
    private static CancellationToken NewTestToken() =>
        new CancellationTokenSource(TimeSpan.FromSeconds(60)).Token;

    [Fact]
    public async Task Events_SseStream_IncludesKindMessageAndDetailFields()
    {
        // --------------------------------------------- seed: progressed + terminal olay
        var userId = Guid.NewGuid();
        Guid runId;
        await using (var context = _fixture.CreateContext())
        {
            var run = await AgentB10TestHost.SeedRunAsync(
                context,
                ownerKey: $"u:{userId:D}",
                status: AgentRunStatus.Completed);
            runId = run.Id;
            await AgentB10TestHost.SeedAppliedEventAsync(
                context, run.Id, 1, "agent.run.progressed",
                payloadJson: """{"event_sequence":1,"kind":"retrieval_started","message":"Makale bölümleri ayrıştırılıyor","detail":{"chunk_count":"12"}}""",
                progressMessage: "Makale içeriği taranıyor...");
            await AgentB10TestHost.SeedAppliedEventAsync(
                context, run.Id, 2, "agent.run.completed",
                payloadJson: """{"event_sequence":2,"selected_mode":"fast","source_scope":"article","usage":{"run_id":"x","recorded_at":"2026-10-13T00:00:00Z"},"answer":"tamam"}""",
                progressMessage: null);
            // Projection applied olayda run.LastEventSequence'i ilerletir; seed bu
            // alanı kendisi yazmaz — projection davranışının son durumu birebir kurulur.
            run.LastEventSequence = 2;
            await context.SaveChangesAsync();
        }

        // --------------------------------------------- mini host: endpoint katmanı
        var cancellationToken = NewTestToken();
        await using var app = BuildSseHost(userId);
        await app.StartAsync(cancellationToken);
        using var client = new HttpClient { BaseAddress = new Uri(app.Urls.First()) };

        using var request = new HttpRequestMessage(HttpMethod.Get, $"/api/v1/agent/runs/{runId:D}/events");
        request.Headers.Accept.ParseAdd("text/event-stream");

        using var response = await client.SendAsync(
            request,
            HttpCompletionOption.ResponseHeadersRead,
            cancellationToken);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.StartsWith("text/event-stream", response.Content.Headers.ContentType?.ToString());

        // --------------------------------------------- SSE gövdesi: olay satırları
        var events = await ReadSseEventsAsync(response, cancellationToken);

        var progressed = events.Single(e => MessageTypeOf(e) == "agent.run.progressed");
        Assert.Equal("retrieval_started", ValueOf(progressed, "kind"));
        Assert.Equal("Makale içeriği taranıyor...", ValueOf(progressed, "message"));
        Assert.Equal("12", ValueOf(progressed, "detail:chunk_count"));

        var completed = events.Single(e => MessageTypeOf(e) == "agent.run.completed");
        Assert.Equal("completed", ValueOf(completed, "kind"));

        // Mevcut alanlar SSE'de korunur + terminal kapanış "done" olayı.
        // (SSE gövdesi anonim nesne serileştirmesi: EventSequence PascalCase.)
        Assert.Equal(1, long.Parse(ValueOf(progressed, "EventSequence")!, System.Globalization.CultureInfo.InvariantCulture));
        var done = events.Last(e => e.Name == "done");
        Assert.Equal("Completed", ValueOf(done, "runStatus"));
        Assert.Equal(2, long.Parse(ValueOf(done, "lastEventSequence"), System.Globalization.CultureInfo.InvariantCulture));
    }

    /// <summary>B5 hub sözleşmesinin replay karşılığı: terminal run + boşalan sayfa
    /// sonrası akış "done" ile kapanır (endpoint SseMaxDuration beklemez).</summary>
    private WebApplication BuildSseHost(Guid userId)
    {
        var builder = WebApplication.CreateBuilder();
        builder.WebHost.UseUrls("http://127.0.0.1:0");

        builder.Services.AddDbContext<AppDbContext>(options => options.UseNpgsql(
            _fixture.TestConnectionString,
            npgsql => npgsql.MigrationsAssembly(typeof(AppDbContext).Assembly.FullName)));
        builder.Services.AddScoped<IApplicationDbContext>(sp => sp.GetRequiredService<AppDbContext>());
        builder.Services.AddMediatR(cfg =>
            cfg.RegisterServicesFromAssembly(typeof(GetAgentRunEventsQueryHandler).Assembly));
        builder.Services.AddSingleton<ICurrentUserService>(new TestCurrentUser(userId));
        builder.Services.AddHttpContextAccessor();
        builder.Services.AddScoped<IAgentGuestSessionService, AgentGuestSessionService>();
        builder.Services.AddApiVersioning(options =>
        {
            options.DefaultApiVersion = new ApiVersion(1, 0);
            options.AssumeDefaultVersionWhenUnspecified = true;
            options.ReportApiVersions = true;
            options.ApiVersionReader = new UrlSegmentApiVersionReader();
        });

        var app = builder.Build();
        app.RegisterAgentEndpoints();
        return app;
    }

    // ------------------------------------------------------------ SSE yardımcıları

    private sealed record SseEvent(string Name, string DataJson);

    private static async Task<List<SseEvent>> ReadSseEventsAsync(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        var events = new List<SseEvent>();
        var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
        using var reader = new StreamReader(stream, Encoding.UTF8);

        string? name = null;
        while (await reader.ReadLineAsync(cancellationToken) is { } line)
        {
            if (line.StartsWith("event: ", StringComparison.Ordinal))
            {
                name = line["event: ".Length..];
            }
            else if (line.StartsWith("data: ", StringComparison.Ordinal) && name is not null)
            {
                events.Add(new SseEvent(name, line["data: ".Length..]));
                name = null;
            }
        }

        Assert.Contains(events, e => e.Name == "done"); // akış kapanmadan bitmemeli
        return events;
    }

    /// <summary>SSE gövdesi anonim nesne serileştirmesidir (System.Text.Json varsayılanı:
    /// PascalCase alanlar + açık camelCase runStatus/lastEventSequence); alan erişimi
    /// büyük/küçük harf duyarsız yapılır. ``detail:chunk_count`` iç içe alan okur.</summary>
    private static string? ValueOf(SseEvent @event, string path)
    {
        using var document = JsonDocument.Parse(@event.DataJson);
        var segments = path.Split(':');
        var current = document.RootElement;
        foreach (var segment in segments)
        {
            if (!TryGetPropertyIgnoreCase(current, segment, out current))
            {
                return null;
            }
        }

        return current.ValueKind == JsonValueKind.String
            ? current.GetString()
            : current.GetRawText();
    }

    private static string? MessageTypeOf(SseEvent @event) => ValueOf(@event, "messageType");

    private static bool TryGetPropertyIgnoreCase(JsonElement element, string name, out JsonElement value)
    {
        foreach (var property in element.EnumerateObject())
        {
            if (string.Equals(property.Name, name, StringComparison.OrdinalIgnoreCase))
            {
                value = property.Value;
                return true;
            }
        }

        value = default;
        return false;
    }
}
