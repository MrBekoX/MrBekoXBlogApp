using System.Text;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;
using BlogApp.Core.Application.Features.AgentFeature.Commands.CancelAgentRunCommand;
using BlogApp.Core.Application.Features.AgentFeature.Commands.RecordAgentFeedbackCommand;
using BlogApp.Core.Application.Features.AgentFeature.Commands.RequestCollaborationResumeCommand;
using BlogApp.Core.Application.Features.AgentFeature.Commands.ResumeAgentRunCommand;
using BlogApp.Core.Application.Features.AgentFeature.Commands.SubmitCollaborationConfirmationCommand;
using BlogApp.Core.Application.Features.AgentFeature.Collaboration;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentObservationsQuery;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunEventsQuery;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunQuery;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Presentation.Api.Helpers;
using BlogApp.Presentation.Api.Services;
using MediatR;

namespace BlogApp.Presentation.Api.Endpoints;

/// <summary>
/// B10 ziyaretçi agent endpoint'leri (plan tablosu, birebir):
///   POST /api/v1/agent/messages            — doğrulanmış istek + outbox; 202 + run_id
///   POST /api/v1/agent/research            — açık deep_research tercihiyle aynı kabul hattı
///   GET  /api/v1/agent/runs/{runId}        — sahiplik kontrolüyle durum + izin verilen sonuç
///   GET  /api/v1/agent/runs/{runId}/events — yetkili replay (JSON) / SSE
///   POST /api/v1/agent/runs/{runId}/cancel — cancel intent + outbox; "iptal isteniyor" kabul durumu
///   POST /api/v1/agent/runs/{runId}/resume — beklenen input/proposal sürümünü doğrulayan devam
///   POST /api/v1/agent/runs/{runId}/collaboration/confirmation — açık gönderim onayı (B9)
///   POST /api/v1/agent/runs/{runId}/collaboration/resume — onaylı proposal için devam isteği (B9)
///   POST /api/v1/agent/feedback            — run sahipliğiyle geri bildirim kaydı
///   GET  /api/v1/agent/admin/observations  — Admin rolüyle yönetim gözlemleri
/// KURALLAR (plan B10): endpoint'ler Python'a HTTP çağrısı YAPMAZ — yazma komutları
/// backend outbox hattına, okumalar backend projection'ına gider. Sahiplik backend'de
/// doğrulanır; istemci owner alanı yetki kaynağı değildir (K5: misafir kimliği sunucu
/// tarafı HttpOnly çerezden çözülür).
/// </summary>
public static class AgentEndpoints
{
    /// <summary>SSE akışının üst süresi; istemci reconnect'te ``after`` imleciyle devam eder.</summary>
    private static readonly TimeSpan SseMaxDuration = TimeSpan.FromSeconds(300);

    private static readonly TimeSpan SsePollInterval = TimeSpan.FromSeconds(2);

    public static IEndpointRouteBuilder RegisterAgentEndpoints(this IEndpointRouteBuilder app)
    {
        var versionedGroup = app.NewVersionedApi("Agent");
        var group = versionedGroup.MapGroup("/api/v{version:apiVersion}/agent")
            .HasApiVersion(1.0)
            .WithTags("Agent");

        // ------------------------------------------------------- POST /messages
        group.MapPost("/messages", async (
            AgentMessageRequestBody body,
            HttpContext httpContext,
            IMediator mediator,
            IAgentGuestSessionService guestSessions,
            CancellationToken cancellationToken) =>
        {
            var guestSessionId = guestSessions.GetOrAssignGuestSessionId();
            var response = await mediator.Send(new AcceptAgentRunCommandRequest
            {
                Question = body.Question,
                Language = string.IsNullOrWhiteSpace(body.Language) ? "tr" : body.Language,
                ModePreference = string.IsNullOrWhiteSpace(body.ModePreference)
                    ? "auto"
                    : body.ModePreference.Trim().ToLowerInvariant(),
                BudgetProfile = string.IsNullOrWhiteSpace(body.BudgetProfile) ? "standard" : body.BudgetProfile,
                ArticleId = body.ArticleId,
                SelectedText = body.SelectedText,
                ConversationId = body.ConversationId,
                IdempotencyKey = string.IsNullOrWhiteSpace(body.IdempotencyKey)
                    ? Guid.NewGuid().ToString("D")
                    : body.IdempotencyKey.Trim(),
                GuestSessionId = guestSessionId,
                // K1/K6: eksikse auto; trim + küçük harf. who_am_i kuralları doğrulayıcıdadır.
                ConversationTopic = AgentConversationTopics.Normalize(body.ConversationTopic),
            }, cancellationToken);

            // 202 Accepted: iş kabul edildi (backend kaydı + outbox); yürütme
            // asenkron hattadır — yanıt "tamamlandı" DEMEZ (plan satır 305).
            return response.IsSuccess
                ? Results.Accepted(
                    $"/api/v1/agent/runs/{response.Value!.RunId:D}",
                    ApiResponse<AgentRunAcceptedDto>.SuccessResult(response.Value))
                : response.ToHttpResult();
        })
        .WithName("PostAgentMessage")
        .WithDescription("Makale/soruya agent işi kabulü; 202 + run_id (outbox hattı)")
        .Produces<ApiResponse<AgentRunAcceptedDto>>(202)
        .Produces<ApiResponse<AgentRunAcceptedDto>>(400)
        .Produces<ApiResponse<AgentRunAcceptedDto>>(401)
        .Produces<ApiResponse<AgentRunAcceptedDto>>(403)
        .Produces<ApiResponse<AgentRunAcceptedDto>>(409)
        .Produces<ApiResponse<AgentRunAcceptedDto>>(503);

        // ------------------------------------------------------- POST /research
        group.MapPost("/research", async (
            AgentResearchRequestBody body,
            HttpContext httpContext,
            IMediator mediator,
            IAgentGuestSessionService guestSessions,
            CancellationToken cancellationToken) =>
        {
            var guestSessionId = guestSessions.GetOrAssignGuestSessionId();
            var response = await mediator.Send(new AcceptAgentRunCommandRequest
            {
                Question = body.Question,
                Language = string.IsNullOrWhiteSpace(body.Language) ? "tr" : body.Language,
                // Açık deep_research tercihi: aynı kabul hattı, mod tercihi sabit (plan satır 513).
                ModePreference = "deep_research",
                BudgetProfile = string.IsNullOrWhiteSpace(body.BudgetProfile) ? "standard" : body.BudgetProfile,
                ArticleId = body.ArticleId,
                SelectedText = body.SelectedText,
                ConversationId = body.ConversationId,
                IdempotencyKey = string.IsNullOrWhiteSpace(body.IdempotencyKey)
                    ? Guid.NewGuid().ToString("D")
                    : body.IdempotencyKey.Trim(),
                GuestSessionId = guestSessionId,
                // /research + who_am_i → 400 validation_error (profil konusu web araştırması başlatamaz).
                ConversationTopic = AgentConversationTopics.Normalize(body.ConversationTopic),
                IsResearchRequest = true,
            }, cancellationToken);

            return response.IsSuccess
                ? Results.Accepted(
                    $"/api/v1/agent/runs/{response.Value!.RunId:D}",
                    ApiResponse<AgentRunAcceptedDto>.SuccessResult(response.Value))
                : response.ToHttpResult();
        })
        .WithName("PostAgentResearch")
        .WithDescription("Açık deep_research tercihiyle agent araştırma kabulü (aynı outbox hattı)")
        .Produces<ApiResponse<AgentRunAcceptedDto>>(202)
        .Produces<ApiResponse<AgentRunAcceptedDto>>(400)
        .Produces<ApiResponse<AgentRunAcceptedDto>>(401)
        .Produces<ApiResponse<AgentRunAcceptedDto>>(403)
        .Produces<ApiResponse<AgentRunAcceptedDto>>(409)
        .Produces<ApiResponse<AgentRunAcceptedDto>>(503);

        // ------------------------------------------------- GET /runs/{runId}
        group.MapGet("/runs/{runId}", async (
            string runId,
            HttpContext httpContext,
            IMediator mediator,
            IAgentGuestSessionService guestSessions,
            CancellationToken cancellationToken) =>
        {
            if (!TryParseRunId(runId, out var parsedRunId))
            {
                return InvalidRunId<AgentRunStatusDto>();
            }

            var response = await mediator.Send(new GetAgentRunQueryRequest
            {
                RunId = parsedRunId,
                GuestSessionId = guestSessions.GetGuestSessionId(),
            }, cancellationToken);

            return response.ToHttpResult();
        })
        .WithName("GetAgentRun")
        .WithDescription("Run durumu + izin verilen sonuç (sahiplik backend'de; B8 sunum denetimi)")
        .Produces<ApiResponse<AgentRunStatusDto>>(200)
        .Produces<ApiResponse<AgentRunStatusDto>>(401)
        .Produces<ApiResponse<AgentRunStatusDto>>(403)
        .Produces<ApiResponse<AgentRunStatusDto>>(404);

        // ------------------------------------------- GET /runs/{runId}/events
        group.MapGet("/runs/{runId}/events", async (
            string runId,
            HttpContext httpContext,
            IMediator mediator,
            IAgentGuestSessionService guestSessions,
            long? after,
            int? limit,
            CancellationToken cancellationToken) =>
        {
            if (!TryParseRunId(runId, out var parsedRunId))
            {
                return InvalidRunId<AgentRunEventsDto>();
            }

            var guestSessionId = guestSessions.GetGuestSessionId();
            var request = new GetAgentRunEventsQueryRequest
            {
                RunId = parsedRunId,
                After = after ?? 0,
                Limit = limit,
                GuestSessionId = guestSessionId,
            };

            // Yetkili replay: text/event-stream istenirse SSE; aksi halde JSON sayfa.
            if (httpContext.Request.Headers.Accept.ToString().Contains("text/event-stream", StringComparison.OrdinalIgnoreCase))
            {
                await StreamEventsAsync(httpContext, mediator, request, cancellationToken);
                return Results.Empty;
            }

            var response = await mediator.Send(request, cancellationToken);
            return response.ToHttpResult();
        })
        .WithName("GetAgentRunEvents")
        .WithDescription("Commit edilmiş projection'dan yetkili replay (JSON) veya SSE akışı")
        .Produces<ApiResponse<AgentRunEventsDto>>(200)
        .Produces<ApiResponse<AgentRunEventsDto>>(401)
        .Produces<ApiResponse<AgentRunEventsDto>>(403)
        .Produces<ApiResponse<AgentRunEventsDto>>(404);

        // ------------------------------------------- POST /runs/{runId}/cancel
        group.MapPost("/runs/{runId}/cancel", async (
            string runId,
            AgentCancelRequestBody? body,
            HttpContext httpContext,
            IMediator mediator,
            IAgentGuestSessionService guestSessions,
            CancellationToken cancellationToken) =>
        {
            if (!TryParseRunId(runId, out var parsedRunId))
            {
                return InvalidRunId<AgentRunCancelDto>();
            }

            var response = await mediator.Send(new CancelAgentRunCommandRequest
            {
                RunId = parsedRunId,
                Reason = body?.Reason,
                GuestSessionId = guestSessions.GetOrAssignGuestSessionId(),
            }, cancellationToken);

            // "requested"/"replay": iptal İSTENİYOR kabul durumu — terminal kararı
            // agent.run.cancelled projection'ıyla gelir (B7/B5).
            return response.IsSuccess
                ? Results.Accepted(
                    $"/api/v1/agent/runs/{parsedRunId:D}",
                    ApiResponse<AgentRunCancelDto>.SuccessResult(response.Value!))
                : response.ToHttpResult();
        })
        .WithName("CancelAgentRun")
        .WithDescription("Cancel intent + outbox; iptal isteniyor kabul durumu (B7)")
        .Produces<ApiResponse<AgentRunCancelDto>>(202)
        .Produces<ApiResponse<AgentRunCancelDto>>(401)
        .Produces<ApiResponse<AgentRunCancelDto>>(403)
        .Produces<ApiResponse<AgentRunCancelDto>>(404);

        // ------------------------------------------- POST /runs/{runId}/resume
        group.MapPost("/runs/{runId}/resume", async (
            string runId,
            AgentResumeRequestBody? body,
            HttpContext httpContext,
            IMediator mediator,
            IAgentGuestSessionService guestSessions,
            CancellationToken cancellationToken) =>
        {
            if (!TryParseRunId(runId, out var parsedRunId))
            {
                return InvalidRunId<AgentRunResumeDto>();
            }

            var response = await mediator.Send(new ResumeAgentRunCommandRequest
            {
                RunId = parsedRunId,
                ExpectedInputVersion = body?.ExpectedInputVersion,
                ExpectedProposalVersion = body?.ExpectedProposalVersion,
                GuestSessionId = guestSessions.GetOrAssignGuestSessionId(),
            }, cancellationToken);

            return response.IsSuccess
                ? Results.Accepted(
                    $"/api/v1/agent/runs/{parsedRunId:D}",
                    ApiResponse<AgentRunResumeDto>.SuccessResult(response.Value!))
                : response.ToHttpResult();
        })
        .WithName("ResumeAgentRun")
        .WithDescription("Beklenen input/proposal sürümünü doğrulayan devam isteği (B9 sözleşmesi)")
        .Produces<ApiResponse<AgentRunResumeDto>>(202)
        .Produces<ApiResponse<AgentRunResumeDto>>(400)
        .Produces<ApiResponse<AgentRunResumeDto>>(401)
        .Produces<ApiResponse<AgentRunResumeDto>>(403)
        .Produces<ApiResponse<AgentRunResumeDto>>(404)
        .Produces<ApiResponse<AgentRunResumeDto>>(409);

        // ----------------------------------------------------- POST /feedback
        group.MapPost("/feedback", async (
            AgentFeedbackRequestBody body,
            HttpContext httpContext,
            IMediator mediator,
            IAgentGuestSessionService guestSessions,
            CancellationToken cancellationToken) =>
        {
            if (!Guid.TryParseExact(body.RunId, "D", out var parsedFeedbackRun))
            {
                return Results.Json(
                    ApiResponse<AgentFeedbackDto>.FailureResult("run_id kanonik UUID olmalıdır."),
                    statusCode: StatusCodes.Status400BadRequest);
            }

            var response = await mediator.Send(new RecordAgentFeedbackCommandRequest
            {
                RunId = parsedFeedbackRun,
                Rating = body.Rating,
                Comment = body.Comment,
                FeedbackKey = string.IsNullOrWhiteSpace(body.FeedbackKey)
                    ? Guid.NewGuid().ToString("D")
                    : body.FeedbackKey.Trim(),
                GuestSessionId = guestSessions.GetOrAssignGuestSessionId(),
            }, cancellationToken);

            return response.IsSuccess
                ? Results.Accepted(
                    $"/api/v1/agent/runs/{parsedFeedbackRun:D}",
                    ApiResponse<AgentFeedbackDto>.SuccessResult(response.Value!))
                : response.ToHttpResult();
        })
        .WithName("RecordAgentFeedback")
        .WithDescription("Run sahipliğiyle geri bildirim kaydı (idempotent)")
        .Produces<ApiResponse<AgentFeedbackDto>>(202)
        .Produces<ApiResponse<AgentFeedbackDto>>(400)
        .Produces<ApiResponse<AgentFeedbackDto>>(401)
        .Produces<ApiResponse<AgentFeedbackDto>>(403)
        .Produces<ApiResponse<AgentFeedbackDto>>(404);

        // --------------------- POST /runs/{runId}/collaboration/confirmation
        group.MapPost("/runs/{runId}/collaboration/confirmation", async (
            string runId,
            AgentCollaborationConfirmationRequestBody body,
            HttpContext httpContext,
            IMediator mediator,
            IAgentGuestSessionService guestSessions,
            CancellationToken cancellationToken) =>
        {
            if (!TryParseRunId(runId, out var parsedRunId))
            {
                return InvalidRunId<AgentCollaborationConfirmationDto>();
            }
            if (!Guid.TryParseExact(body.ProposalId, "D", out var parsedProposalId))
            {
                return Results.Json(
                    ApiResponse<AgentCollaborationConfirmationDto>.FailureResult(
                        "proposal_id kanonik UUID olmalıdır."),
                    statusCode: StatusCodes.Status400BadRequest);
            }

            var response = await mediator.Send(new SubmitCollaborationConfirmationRequest
            {
                RunId = parsedRunId,
                ProposalId = parsedProposalId,
                SubmittedContentHash = body.SubmittedContentHash,
                EditedSummary = body.EditedSummary,
                GuestSessionId = guestSessions.GetOrAssignGuestSessionId(),
            }, cancellationToken);

            return response.IsSuccess
                ? Results.Accepted(
                    $"/api/v1/agent/runs/{parsedRunId:D}",
                    ApiResponse<AgentCollaborationConfirmationDto>.SuccessResult(
                        ToConfirmationDto(parsedRunId, parsedProposalId, response.Value!)))
                : response.ToHttpResult();
        })
        .WithName("SubmitCollaborationConfirmation")
        .WithDescription("Açık gönderim onayı (B9): proposal sürüm hash'i + sahiplik + süre doğrulaması; kabul AgentActionResultV1'i outbox'a yazar")
        .Produces<ApiResponse<AgentCollaborationConfirmationDto>>(202)
        .Produces<ApiResponse<AgentCollaborationConfirmationDto>>(400)
        .Produces<ApiResponse<AgentCollaborationConfirmationDto>>(401)
        .Produces<ApiResponse<AgentCollaborationConfirmationDto>>(403)
        .Produces<ApiResponse<AgentCollaborationConfirmationDto>>(404)
        .Produces<ApiResponse<AgentCollaborationConfirmationDto>>(409);

        // ---------------------------- POST /runs/{runId}/collaboration/resume
        group.MapPost("/runs/{runId}/collaboration/resume", async (
            string runId,
            AgentCollaborationResumeRequestBody body,
            HttpContext httpContext,
            IMediator mediator,
            IAgentGuestSessionService guestSessions,
            CancellationToken cancellationToken) =>
        {
            if (!TryParseRunId(runId, out var parsedRunId))
            {
                return InvalidRunId<AgentCollaborationResumeDto>();
            }
            if (!Guid.TryParseExact(body.ProposalId, "D", out var parsedProposalId))
            {
                return Results.Json(
                    ApiResponse<AgentCollaborationResumeDto>.FailureResult(
                        "proposal_id kanonik UUID olmalıdır."),
                    statusCode: StatusCodes.Status400BadRequest);
            }

            var response = await mediator.Send(new RequestCollaborationResumeRequest
            {
                RunId = parsedRunId,
                ProposalId = parsedProposalId,
                ExpectedContentHash = body.ExpectedContentHash,
                GuestSessionId = guestSessions.GetOrAssignGuestSessionId(),
            }, cancellationToken);

            return response.IsSuccess
                ? Results.Accepted(
                    $"/api/v1/agent/runs/{parsedRunId:D}",
                    ApiResponse<AgentCollaborationResumeDto>.SuccessResult(
                        ToResumeDto(parsedRunId, parsedProposalId, response.Value!)))
                : response.ToHttpResult();
        })
        .WithName("RequestCollaborationResume")
        .WithDescription("Onaylı iş birliği proposal'ı için devam isteği (B9): aynı onay için ikinci resume ÜRETİLMEZ (Duplicate)")
        .Produces<ApiResponse<AgentCollaborationResumeDto>>(202)
        .Produces<ApiResponse<AgentCollaborationResumeDto>>(400)
        .Produces<ApiResponse<AgentCollaborationResumeDto>>(401)
        .Produces<ApiResponse<AgentCollaborationResumeDto>>(403)
        .Produces<ApiResponse<AgentCollaborationResumeDto>>(404)
        .Produces<ApiResponse<AgentCollaborationResumeDto>>(409);

        // ------------------------------------------------ GET /admin/observations
        group.MapGet("/admin/observations", async (
            int? windowHours,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new GetAgentObservationsQueryRequest
            {
                WindowHours = windowHours ?? 24,
            }, cancellationToken);

            return response.ToHttpResult();
        })
        .RequireAuthorization(policy => policy.RequireRole("Admin"))
        .WithName("GetAgentObservations")
        .WithDescription("Yönetim gözlemleri: backlog, outbox gecikmesi, projection sayıları, iş süreleri, geri bildirim (Admin)")
        .Produces<ApiResponse<AgentObservationsDto>>(200)
        .Produces<ApiResponse<AgentObservationsDto>>(401)
        .Produces<ApiResponse<AgentObservationsDto>>(403);

        return app;
    }

    /// <summary>SSE akışı: commit edilmiş projection'dan replay + 2 sn'lik yapışkan
    /// yoklama. Terminal olaydan sonra kapanır; ``after`` imleciyle istemci
    /// reconnect kaldığı yerden sürer. Sahiplik her olay sayfasında yeniden
    /// doğrulanır (aynı yetkilendirilmiş replay sorgusu üzerinden).</summary>
    private static async Task StreamEventsAsync(
        HttpContext httpContext,
        IMediator mediator,
        GetAgentRunEventsQueryRequest request,
        CancellationToken cancellationToken)
    {
        var response = httpContext.Response;
        response.StatusCode = StatusCodes.Status200OK;
        response.ContentType = "text/event-stream; charset=utf-8";
        response.Headers.CacheControl = "no-cache";
        response.Headers["X-Accel-Buffering"] = "no";

        var startedAt = DateTimeOffset.UtcNow;
        var cursor = request.After;

        try
        {
            while (!cancellationToken.IsCancellationRequested
                   && DateTimeOffset.UtcNow - startedAt < SseMaxDuration)
            {
                var page = await mediator.Send(request with { After = cursor }, cancellationToken);
                if (page.IsFailure)
                {
                    // Sahiplik oturumu koptu / run silindi: akışı sonlandır.
                    await WriteSseEventAsync(response, "error",
                        page.Errors.FirstOrDefault() ?? "replay hatası", cancellationToken);
                    return;
                }

                foreach (var item in page.Value!.Events)
                {
                    var payload = System.Text.Json.JsonSerializer.Serialize(new
                    {
                        item.EventSequence,
                        item.MessageType,
                        item.MessageId,
                        item.OccurredAt,
                        // Ortak olay yüzeyi (agent live-steps, ADDITIVE): JSON
                        // replay ile AYNI türetme (handler DTO'su) paylaşılır.
                        item.Kind,
                        item.Message,
                        item.Detail,
                        runStatus = page.Value.RunStatus,
                        lastEventSequence = page.Value.LastEventSequence,
                    });
                    await WriteSseEventAsync(response, "agent-event", payload, cancellationToken);
                    cursor = Math.Max(cursor, item.EventSequence);
                }

                // Terminal: kalan olaylar boşaldıysa akış tamamlandı.
                var isTerminal = page.Value.RunStatus is "Completed" or "PartiallyCompleted" or "Failed" or "Cancelled";
                if (isTerminal && !page.Value.HasMore)
                {
                    await WriteSseEventAsync(response, "done",
                        System.Text.Json.JsonSerializer.Serialize(new
                        {
                            runStatus = page.Value.RunStatus,
                            lastEventSequence = page.Value.LastEventSequence,
                        }), cancellationToken);
                    return;
                }

                if (!page.Value.HasMore)
                {
                    await Task.Delay(SsePollInterval, cancellationToken);
                }
            }

            await WriteSseEventAsync(response, "timeout",
                System.Text.Json.JsonSerializer.Serialize(new { after = cursor }), cancellationToken);
        }
        catch (OperationCanceledException)
        {
            // İstemci bağlantıyı kesti: normal kapanış.
        }
    }

    private static async Task WriteSseEventAsync(HttpResponse response, string eventName, string data, CancellationToken cancellationToken)
    {
        var builder = new StringBuilder()
            .Append("event: ").Append(eventName).Append('\n')
            .Append("data: ").Append(data).Append("\n\n");
        var bytes = Encoding.UTF8.GetBytes(builder.ToString());
        await response.Body.WriteAsync(bytes, cancellationToken);
        await response.Body.FlushAsync(cancellationToken);
    }

    private static bool TryParseRunId(string raw, out Guid runId)
    {
        runId = Guid.Empty;
        return Guid.TryParseExact(raw, "D", out runId);
    }

    private static AgentCollaborationConfirmationDto ToConfirmationDto(
        Guid runId, Guid proposalId, CollaborateSubmitResult result) =>
        new(
            runId,
            proposalId,
            Outcome: result.Outcome.ToString().ToLowerInvariant(),
            Version: result.Version,
            RegisteredAt: result.RegisteredAt,
            RejectionReason: result.RejectionReason);

    private static AgentCollaborationResumeDto ToResumeDto(
        Guid runId, Guid proposalId, CollaborateResumeResult result) =>
        new(
            runId,
            proposalId,
            Outcome: result.Outcome.ToString().ToLowerInvariant(),
            SentAt: result.SentAt,
            RejectionReason: result.RejectionReason);

    private static IResult InvalidRunId<T>() =>
        Results.Json(
            ApiResponse<T>.FailureResult("run_id kanonik UUID olmalıdır."),
            statusCode: StatusCodes.Status400BadRequest);
}

/// <summary>POST /messages gövdesi; alan adları istemciye camelCase olarak döner.
/// <c>conversationTopic</c>: <c>auto</c> (varsayılan) | <c>who_am_i</c> (K1).</summary>
public sealed record AgentMessageRequestBody(
    string Question,
    string? Language,
    string? ModePreference,
    string? BudgetProfile,
    Guid? ArticleId,
    string? SelectedText,
    Guid? ConversationId,
    string? IdempotencyKey,
    string? ConversationTopic = null);

/// <summary>POST /research gövdesi: mod tercihi deep_research sabittir (açık araştırma).
/// <c>conversationTopic=who_am_i</c> burada reddedilir (400).</summary>
public sealed record AgentResearchRequestBody(
    string Question,
    string? Language,
    string? BudgetProfile,
    Guid? ArticleId,
    string? SelectedText,
    Guid? ConversationId,
    string? IdempotencyKey,
    string? ConversationTopic = null);

public sealed record AgentCancelRequestBody(string? Reason);

/// <summary>POST /runs/{runId}/resume gövdesi: beklenen sürümler en az biri verilerek
/// doğrulanır (B9 sözleşmesi; istemcinin gördüğü state'in gerilememiş olması şartı).</summary>
public sealed record AgentResumeRequestBody(long? ExpectedInputVersion, long? ExpectedProposalVersion);

public sealed record AgentFeedbackRequestBody(string RunId, int Rating, string? Comment, string? FeedbackKey);

/// <summary>POST /runs/{runId}/collaboration/confirmation gövdesi (B9): hash
/// ziyaretçinin onayladığı (varsa düzenlediği) sürümün özet metninin SHA-256
/// özetidir; düzenleme + onay tek çağrıdır (EditedSummary verilirse hash
/// düzenlenen metnin özeti olmak zorundadır — backend doğrular).</summary>
public sealed record AgentCollaborationConfirmationRequestBody(
    string ProposalId,
    string SubmittedContentHash,
    string? EditedSummary);

/// <summary>POST /runs/{runId}/collaboration/resume gövdesi (B9): beklenen hash
/// istemcinin gördüğü onaylı sürümdür; uyuşmazlık 409'dur.</summary>
public sealed record AgentCollaborationResumeRequestBody(string ProposalId, string ExpectedContentHash);

/// <summary>Onay sonucu DTO'su: outcome string olarak taşınır (accepted|duplicate|
/// rejected_owner|rejected_version); 202 yalnız accepted|duplicate içindir.</summary>
public sealed record AgentCollaborationConfirmationDto(
    Guid RunId,
    Guid ProposalId,
    string Outcome,
    long Version,
    DateTimeOffset RegisteredAt,
    string? RejectionReason);

/// <summary>Devam isteği sonucu DTO'su: outcome string (sent|duplicate|
/// rejected_owner|rejected_version); 202 yalnız sent|duplicate içindir.</summary>
public sealed record AgentCollaborationResumeDto(
    Guid RunId,
    Guid ProposalId,
    string Outcome,
    DateTimeOffset SentAt,
    string? RejectionReason);
