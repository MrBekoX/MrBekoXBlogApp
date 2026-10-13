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

    // ------------------------------------------------- çok adımlı progressed dizisi

    [Fact]
    public async Task Events_MultiStepProgressedSequence_PreservesKindMessageDetailAndOrder()
    {
        // Canlı adım dizisi: her progressed olayı kendi kind/message/detail'ini
        // taşır; sıra event_sequence'e göredir. kind kümesi yüzeyde KAPALI
        // DEĞİLDİR: agent_core yeni bir kind (ör. tool_error) ürettiğinde
        // payload.kind aynen akar (araç hatası da kullanıcıya görünür).
        var userId = Guid.NewGuid();
        var context = _fixture.CreateContext();
        var run = await AgentB10TestHost.SeedRunAsync(context, ownerKey: $"u:{userId:D}");
        await AgentB10TestHost.SeedAppliedEventAsync(
            context, run.Id, 1, "agent.run.progressed",
            payloadJson: """{"event_sequence":1,"kind":"research_started","message":"araştırma başladı"}""",
            progressMessage: "araştırma başladı");
        await AgentB10TestHost.SeedAppliedEventAsync(
            context, run.Id, 2, "agent.run.progressed",
            payloadJson: """{"event_sequence":2,"kind":"tool_error","message":"kaynak bulunamadı veya kaldırıldı (HTTP 404)","detail":{"node":"research.gather","code":"not_found"}}""",
            progressMessage: "kaynak bulunamadı veya kaldırıldı (HTTP 404)");
        await AgentB10TestHost.SeedAppliedEventAsync(
            context, run.Id, 3, "agent.run.progressed",
            payloadJson: """{"event_sequence":3,"kind":"generation_started","message":"rapor üretiliyor"}""",
            progressMessage: "rapor üretiliyor");

        var result = await CreateHandler(userId).Handle(
            new GetAgentRunEventsQueryRequest { RunId = run.Id }, CancellationToken.None);

        Assert.True(result.IsSuccess);
        var events = result.Value!.Events;
        Assert.Equal(3, events.Count);
        Assert.Equal(new long[] { 1, 2, 3 }, events.Select(e => e.EventSequence).ToArray());
        Assert.Equal(new[] { "research_started", "tool_error", "generation_started" }, events.Select(e => e.Kind));
        Assert.Equal("araştırma başladı", events[0].Message);
        Assert.Equal("kaynak bulunamadı veya kaldırıldı (HTTP 404)", events[1].Message);
        Assert.NotNull(events[1].Detail);
        Assert.Equal("research.gather", events[1].Detail!["node"]);
        Assert.Equal("not_found", events[1].Detail["code"]);
        Assert.Equal("rapor üretiliyor", events[2].Message);
    }

    // ------------------------------------------------- sayfalama: after/limit/HasMore

    [Fact]
    public async Task Events_LimitPagesWithAfterCursor_AndHasMoreFlags()
    {
        // Yenileme replay'i sözleşmesi: Limit sayfa boyu, After imleci,
        // HasMore = (dönen satır sayısı == pageSize) semantiği.
        var userId = Guid.NewGuid();
        var context = _fixture.CreateContext();
        var run = await AgentB10TestHost.SeedRunAsync(context, ownerKey: $"u:{userId:D}");
        for (var sequence = 1; sequence <= 5; sequence++)
        {
            await AgentB10TestHost.SeedAppliedEventAsync(
                context, run.Id, sequence, "agent.run.progressed",
                payloadJson: $$"""{"event_sequence":{{sequence}},"kind":"retrieval_started","message":"adım {{sequence}}"}""",
                progressMessage: $"adım {sequence}");
        }

        var handler = CreateHandler(userId);

        var page1 = await handler.Handle(
            new GetAgentRunEventsQueryRequest { RunId = run.Id, Limit = 2 }, CancellationToken.None);
        Assert.True(page1.IsSuccess);
        Assert.Equal(new long[] { 1, 2 }, page1.Value!.Events.Select(e => e.EventSequence).ToArray());
        Assert.True(page1.Value!.HasMore); // count == pageSize → devam var

        var page2 = await handler.Handle(
            new GetAgentRunEventsQueryRequest { RunId = run.Id, Limit = 2, After = 2 }, CancellationToken.None);
        Assert.True(page2.IsSuccess);
        Assert.Equal(new long[] { 3, 4 }, page2.Value!.Events.Select(e => e.EventSequence).ToArray());
        Assert.True(page2.Value!.HasMore);

        var page3 = await handler.Handle(
            new GetAgentRunEventsQueryRequest { RunId = run.Id, Limit = 2, After = 4 }, CancellationToken.None);
        Assert.True(page3.IsSuccess);
        var lastPage = Assert.Single(page3.Value!.Events);
        Assert.Equal(5, lastPage.EventSequence);
        Assert.False(page3.Value!.HasMore); // son sayfa: count < pageSize
    }

    [Fact]
    public async Task Events_LimitOutsideBounds_ClampsToMaxPageSize()
    {
        // MaxPageSize=200 sınırı: limit üstü/altı istekler 200'e kestirilir;
        // 201 olayla HasMore=true ve kalan tek satır After imleciyle gelir.
        var userId = Guid.NewGuid();
        Guid runId;
        await using (var context = _fixture.CreateContext())
        {
            var run = await AgentB10TestHost.SeedRunAsync(context, ownerKey: $"u:{userId:D}");
            runId = run.Id;
            for (var sequence = 1; sequence <= GetAgentRunEventsQueryHandler.MaxPageSize + 1; sequence++)
            {
                context.AgentEventInboxes.Add(new BlogApp.Core.Domain.Entities.AgentEventInbox
                {
                    ConsumerName = "backend-agent-events",
                    MessageId = Guid.NewGuid(),
                    MessageType = "agent.run.progressed",
                    RunId = run.Id,
                    EventSequence = sequence,
                    Status = "applied",
                    PayloadJson = $$"""{"event_sequence":{{sequence}},"kind":"retrieval_started","message":"adım {{sequence}}"}""",
                    ProgressMessage = $"adım {sequence}",
                    CreatedAt = DateTime.UtcNow,
                });
            }
            await context.SaveChangesAsync();
        }

        var handler = CreateHandler(userId);

        // Sınır üstü limit → MaxPageSize'e kestirilir.
        var clamped = await handler.Handle(
            new GetAgentRunEventsQueryRequest { RunId = runId, Limit = 500 }, CancellationToken.None);
        Assert.True(clamped.IsSuccess);
        Assert.Equal(GetAgentRunEventsQueryHandler.MaxPageSize, clamped.Value!.Events.Count);
        Assert.True(clamped.Value!.HasMore);
        Assert.Equal(1, clamped.Value!.Events[0].EventSequence);
        Assert.Equal(GetAgentRunEventsQueryHandler.MaxPageSize, clamped.Value!.Events[^1].EventSequence);

        // Limit verilmemesi de aynı üst sayfayı üretir.
        var defaulted = await handler.Handle(
            new GetAgentRunEventsQueryRequest { RunId = runId }, CancellationToken.None);
        Assert.True(defaulted.IsSuccess);
        Assert.Equal(GetAgentRunEventsQueryHandler.MaxPageSize, defaulted.Value!.Events.Count);
        Assert.True(defaulted.Value!.HasMore);

        // Kalan son satır imleçle gelir; son sayfada HasMore düşer.
        var rest = await handler.Handle(
            new GetAgentRunEventsQueryRequest
            {
                RunId = runId,
                After = GetAgentRunEventsQueryHandler.MaxPageSize,
            }, CancellationToken.None);
        Assert.True(rest.IsSuccess);
        var remaining = Assert.Single(rest.Value!.Events);
        Assert.Equal(GetAgentRunEventsQueryHandler.MaxPageSize + 1, remaining.EventSequence);
        Assert.False(rest.Value!.HasMore);
    }
}
