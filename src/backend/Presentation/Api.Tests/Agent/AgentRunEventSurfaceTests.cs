using System.Text.Json;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunEventsQuery;
using BlogApp.Core.Domain.Enums;
using BlogApp.Infrastructure.Persistence;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Agent;

/// <summary>
/// Agent live-steps ortak olay yüzeyi (ADDITIVE): GET /runs/{runId}/events replay'i,
/// projection'ın applied kayda yazdığı PayloadJson + ProgressMessage sütunlarından
/// ``kind`` / ``message`` / ``detail`` türetir. Sözleşme:
///   - progressed: kind = payload.kind; message = saklanan kullanıcı-dostu cümle;
///     detail = payload.detail (değer başına 500 karakterle kesilir),
///   - terminal: kind messageType son ekinden (completed | partial | failed |
///     cancelled); agent.action.proposed → action_proposed,
///   - bozuk/eksik payload: üç alan null, olay DÜŞMEZ, istek başarılı (endpoint 200),
///   - migration öncesi eski satırlar (payload NULL): aynı null davranışı.
/// Mevcut dört alan (eventSequence/messageType/messageId/occurredAt) değişmeden korunur.
/// </summary>
[Collection("agent-b10")]
public class AgentRunEventSurfaceTests : IAsyncLifetime
{
    private readonly AgentB10DatabaseFixture _fixture;

    public AgentRunEventSurfaceTests(AgentB10DatabaseFixture fixture) => _fixture = fixture;

    public Task InitializeAsync() => _fixture.ResetAsync();

    public Task DisposeAsync() => Task.CompletedTask;

    private GetAgentRunEventsQueryHandler CreateHandler(Guid userId) =>
        new(_fixture.CreateContext(), new TestCurrentUser(userId));

    // ------------------------------------------------- progressed: kind/message/detail

    [Fact]
    public async Task Events_ProgressedEvent_ReturnsKindMessageAndDetail()
    {
        var userId = Guid.NewGuid();
        var context = _fixture.CreateContext();
        var run = await AgentB10TestHost.SeedRunAsync(context, ownerKey: $"u:{userId:D}");
        await AgentB10TestHost.SeedAppliedEventAsync(
            context, run.Id, 1, "agent.run.progressed",
            payloadJson: """{"event_sequence":1,"kind":"retrieval_started","message":"Makale bölümleri ayrıştırılıyor","detail":{"chunk_count":"12","strategy":"hybrid"}}""",
            progressMessage: "Makale içeriği taranıyor...");

        var result = await CreateHandler(userId).Handle(
            new GetAgentRunEventsQueryRequest { RunId = run.Id }, CancellationToken.None);

        Assert.True(result.IsSuccess);
        var @event = Assert.Single(result.Value!.Events);
        Assert.Equal(1, @event.EventSequence);
        Assert.Equal("agent.run.progressed", @event.MessageType);
        Assert.Equal("retrieval_started", @event.Kind);
        Assert.Equal("Makale içeriği taranıyor...", @event.Message);
        Assert.NotNull(@event.Detail);
        Assert.Equal("12", @event.Detail!["chunk_count"]);
        Assert.Equal("hybrid", @event.Detail["strategy"]);
    }

    [Fact]
    public async Task Events_ProgressedDetail_ValuesTruncatedAt500Chars()
    {
        var userId = Guid.NewGuid();
        var context = _fixture.CreateContext();
        var run = await AgentB10TestHost.SeedRunAsync(context, ownerKey: $"u:{userId:D}");
        var longValue = new string('x', 700);
        await AgentB10TestHost.SeedAppliedEventAsync(
            context, run.Id, 1, "agent.run.progressed",
            payloadJson: JsonSerializer.Serialize(new
            {
                event_sequence = 1,
                kind = "generation_started",
                message = "Yanıt üretiliyor",
                detail = new Dictionary<string, string>
                {
                    ["oversized"] = longValue,
                    ["short"] = "ok",
                },
            }),
            progressMessage: "Yanıt üretiliyor");

        var result = await CreateHandler(userId).Handle(
            new GetAgentRunEventsQueryRequest { RunId = run.Id }, CancellationToken.None);

        Assert.True(result.IsSuccess);
        var @event = Assert.Single(result.Value!.Events);
        Assert.NotNull(@event.Detail);
        Assert.Equal(500, @event.Detail!["oversized"].Length); // değer başına 500 karakter
        Assert.Equal("ok", @event.Detail["short"]);
    }

    // ------------------------------------------------- terminal + action.proposed kind

    [Fact]
    public async Task Events_TerminalAndProposalEvents_DeriveKindFromMessageTypeSuffix()
    {
        var userId = Guid.NewGuid();
        var context = _fixture.CreateContext();
        var run = await AgentB10TestHost.SeedRunAsync(
            context, ownerKey: $"u:{userId:D}", status: AgentRunStatus.Completed);
        await AgentB10TestHost.SeedAppliedEventAsync(context, run.Id, 1, "agent.run.accepted");
        await AgentB10TestHost.SeedAppliedEventAsync(context, run.Id, 2, "agent.run.completed");
        await AgentB10TestHost.SeedAppliedEventAsync(context, run.Id, 3, "agent.run.partially_completed");
        await AgentB10TestHost.SeedAppliedEventAsync(context, run.Id, 4, "agent.run.failed");
        await AgentB10TestHost.SeedAppliedEventAsync(context, run.Id, 5, "agent.run.cancelled");
        await AgentB10TestHost.SeedAppliedEventAsync(context, run.Id, 6, "agent.action.proposed");

        var result = await CreateHandler(userId).Handle(
            new GetAgentRunEventsQueryRequest { RunId = run.Id }, CancellationToken.None);

        Assert.True(result.IsSuccess);
        var byType = result.Value!.Events.ToDictionary(e => e.MessageType, e => e);
        Assert.Equal("completed", byType["agent.run.completed"].Kind);
        Assert.Equal("partial", byType["agent.run.partially_completed"].Kind);
        Assert.Equal("failed", byType["agent.run.failed"].Kind);
        Assert.Equal("cancelled", byType["agent.run.cancelled"].Kind);
        Assert.Equal("action_proposed", byType["agent.action.proposed"].Kind);
        // Sözleşme dışı tür (accepted): kind yok.
        Assert.Null(byType["agent.run.accepted"].Kind);
        // Terminal/action olaylarında message/detail taşınmaz.
        Assert.All(result.Value!.Events, e =>
        {
            if (e.MessageType != "agent.run.progressed")
            {
                Assert.Null(e.Message);
                Assert.Null(e.Detail);
            }
        });
    }

    // ------------------------------------------------- bozuk payload: alanlar null, olay düşmez

    [Fact]
    public async Task Events_CorruptPayload_ReturnsEventWithNullFields()
    {
        var userId = Guid.NewGuid();
        var context = _fixture.CreateContext();
        var run = await AgentB10TestHost.SeedRunAsync(context, ownerKey: $"u:{userId:D}");
        await AgentB10TestHost.SeedAppliedEventAsync(
            context, run.Id, 1, "agent.run.progressed",
            payloadJson: "{\"kind\": bozuk json", // saklaması bozulmuş satır
            progressMessage: "Kaynaklar taranıyor...");

        var result = await CreateHandler(userId).Handle(
            new GetAgentRunEventsQueryRequest { RunId = run.Id }, CancellationToken.None);

        // Handler başarılı döner → endpoint 200; olay düşmez, yalnız türetilen alanlar null.
        Assert.True(result.IsSuccess);
        var @event = Assert.Single(result.Value!.Events);
        Assert.Equal(1, @event.EventSequence);
        Assert.Null(@event.Kind);
        Assert.Null(@event.Message);
        Assert.Null(@event.Detail);
    }

    // ------------------------------------------------- eski satır uyumu (payload NULL)

    [Fact]
    public async Task Events_LegacyRowWithoutPayload_ReturnsSuccessWithNullFields()
    {
        var userId = Guid.NewGuid();
        var context = _fixture.CreateContext();
        var run = await AgentB10TestHost.SeedRunAsync(context, ownerKey: $"u:{userId:D}");
        // Migration öncesi satır: payload sütunları NULL.
        await AgentB10TestHost.SeedAppliedEventAsync(context, run.Id, 1, "agent.run.progressed");

        var result = await CreateHandler(userId).Handle(
            new GetAgentRunEventsQueryRequest { RunId = run.Id }, CancellationToken.None);

        Assert.True(result.IsSuccess);
        var @event = Assert.Single(result.Value!.Events);
        Assert.Equal("agent.run.progressed", @event.MessageType);
        Assert.Null(@event.Kind);
        Assert.Null(@event.Message);
        Assert.Null(@event.Detail);
    }
}
