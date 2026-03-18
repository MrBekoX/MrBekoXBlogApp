using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Server.Api.Extensions;
using BlogApp.Server.Application.Common.Constants;
using BlogApp.Server.Application.Common.Events;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Domain.Enums;

namespace BlogApp.Server.Api.Endpoints;

public static class ChatEndpoints
{
    public static IEndpointRouteBuilder RegisterChatEndpoints(this IEndpointRouteBuilder app)
    {
        var versionedGroup = app.NewVersionedApi("Chat");
        var group = versionedGroup.MapGroup("/api/v{version:apiVersion}/chat")
            .HasApiVersion(1.0)
            .WithTags("Chat");

        group.MapPost("/message", async (
            ChatMessageRequest request,
            IAsyncOperationDispatcher dispatcher,
            IUnitOfWork unitOfWork,
            IChatSessionTokenService chatSessionTokenService,
            IChatAbuseProtectionService chatAbuseProtectionService,
            IQueueDepthService queueDepthService,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            var post = await unitOfWork.PostsRead.GetByIdAsync(request.PostId, cancellationToken);
            if (post is null || post.Status != PostStatus.Published)
            {
                return Results.NotFound(ApiResponse<object>.FailureResult("Post not found"));
            }

            if (!IdempotencyEndpointHelper.TryResolveOperationId(httpContext, request.OperationId, out var operationId, out var operationError))
            {
                return operationError!;
            }

            var sessionId = ResolveSessionId(request.SessionId);
            if (sessionId is null)
            {
                return Results.BadRequest(ApiResponse<object>.FailureResult("Invalid sessionId."));
            }

            var history = request.ConversationHistory?
                .Select(h => new ChatHistoryItem
                {
                    Role = h.Role,
                    Content = h.Content
                })
                .ToList() ?? [];

            var subject = httpContext.User.ToPostAuthorizationSubject();
            if (!subject.IsAuthenticated)
            {
                var abuseDecision = await chatAbuseProtectionService.AuthorizeAnonymousAsync(
                    new AnonymousChatRequest(
                        request.PostId,
                        sessionId,
                        request.Message,
                        history.Count,
                        request.ClientFingerprint,
                        request.TurnstileToken,
                        ResolveClientIp(httpContext)),
                    cancellationToken);

                if (!abuseDecision.Allowed)
                {
                    return BuildRejectedResponse(abuseDecision);
                }
            }

            var circuitState = await queueDepthService.GetCircuitStateAsync(cancellationToken);
            if (string.Equals(circuitState, "open", StringComparison.OrdinalIgnoreCase))
            {
                return Results.Json(
                    ApiResponse<object>.FailureResult("AI assistant is currently unavailable. Please try again later."),
                    statusCode: StatusCodes.Status503ServiceUnavailable);
            }

            var chatDepth = await queueDepthService.GetQueueDepthAsync(
                MessagingConstants.QueueNames.ChatRequests, cancellationToken);
            var estimatedWaitSeconds = chatDepth.IsStale ? (int?)null : chatDepth.Depth * 15;

            var dispatch = await dispatcher.DispatchAsync(
                new AsyncOperationDispatchRequest<ChatRequestedEvent>(
                    EndpointName: "chat.message",
                    OperationId: operationId,
                    RequestPayload: new
                    {
                        request.PostId,
                        request.Message,
                        SessionId = sessionId,
                        request.ConversationHistory,
                        Language = request.Language ?? "tr",
                        request.EnableWebSearch
                    },
                    UserId: subject.UserId,
                    SessionId: sessionId,
                    ResourceId: request.PostId.ToString(),
                    BuildEvent: (correlationId, opId, causationId) => new ChatRequestedEvent
                    {
                        OperationId = opId,
                        CorrelationId = correlationId,
                        CausationId = causationId,
                        Payload = new ChatRequestPayload
                        {
                            SessionId = sessionId,
                            PostId = request.PostId,
                            ArticleTitle = post.Title,
                            ArticleContent = post.Content,
                            UserMessage = request.Message,
                            ConversationHistory = history,
                            Language = request.Language ?? "tr",
                            EnableWebSearch = request.EnableWebSearch,
                            AuthContext = new ChatAuthorizationContext
                            {
                                SubjectType = subject.IsAuthenticated ? "user" : "anonymous",
                                SubjectId = subject.UserId?.ToString(),
                                Roles = subject.Roles.ToList(),
                                Fingerprint = request.ClientFingerprint
                            }
                        }
                    },
                    RoutingKey: MessagingConstants.RoutingKeys.ChatMessageRequested,
                    AcceptedStatusCode: StatusCodes.Status202Accepted,
                    BuildAcceptedResponse: (opId, correlationId) =>
                    {
                        var sessionToken = chatSessionTokenService.IssueToken(new ChatSessionTokenIssueRequest(
                            sessionId,
                            request.PostId,
                            opId,
                            correlationId,
                            request.ClientFingerprint));

                        return ApiResponse<object>.SuccessResult(
                            new
                            {
                                operationId = opId,
                                correlationId,
                                sessionId,
                                sessionToken = sessionToken.Token,
                                sessionTokenExpiresAt = sessionToken.ExpiresAt,
                                estimatedWaitSeconds,
                                circuitState
                            },
                            "Chat request accepted");
                    }),
                cancellationToken);

            if (dispatch.State == AsyncOperationDispatchState.Conflict)
            {
                return IdempotencyEndpointHelper.BuildConflict(dispatch.ErrorMessage ?? "The same operationId was used with a different payload.");
            }

            if (dispatch.State == AsyncOperationDispatchState.Failed)
            {
                if (string.Equals(dispatch.ErrorCode, AsyncOperationErrorCodes.AsyncDispatchUnavailable, StringComparison.Ordinal))
                {
                    return Results.Json(
                        ApiResponse<object>.FailureResult(dispatch.ErrorMessage ?? "Chat is temporarily unavailable."),
                        statusCode: StatusCodes.Status503ServiceUnavailable);
                }

                return Results.BadRequest(ApiResponse<object>.FailureResult(dispatch.ErrorMessage ?? "Chat request could not be dispatched."));
            }

            return IdempotencyEndpointHelper.BuildStoredResponse(dispatch.Response);
        })
        .WithName("SendChatMessage")
        .AllowAnonymous()
        .Produces(StatusCodes.Status202Accepted)
        .Produces(StatusCodes.Status200OK)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status404NotFound)
        .ProducesProblem(StatusCodes.Status409Conflict)
        .ProducesProblem(StatusCodes.Status429TooManyRequests)
        .ProducesProblem(StatusCodes.Status503ServiceUnavailable);

        return app;
    }

    private static IResult BuildRejectedResponse(ChatAbuseDecision decision)
    {
        var payload = new ApiResponse<object>
        {
            Success = false,
            Message = decision.Message,
            Errors = [decision.Message],
            Data = new
            {
                requiresTurnstile = decision.RequiresTurnstile,
                retryAfterSeconds = decision.RetryAfterSeconds
            }
        };

        var statusCode = decision.ServiceUnavailable
            ? StatusCodes.Status503ServiceUnavailable
            : StatusCodes.Status429TooManyRequests;

        return Results.Json(payload, statusCode: statusCode);
    }

    private static string? ResolveSessionId(string? sessionId)
    {
        if (string.IsNullOrWhiteSpace(sessionId))
        {
            return Guid.NewGuid().ToString("D");
        }

        return Guid.TryParse(sessionId, out var parsed)
            ? parsed.ToString("D")
            : null;
    }

    private static string? ResolveClientIp(HttpContext httpContext)
    {
        var remoteIp = httpContext.Connection.RemoteIpAddress?.ToString();
        if (!string.IsNullOrWhiteSpace(remoteIp))
        {
            return remoteIp;
        }

        var forwardedFor = httpContext.Request.Headers["X-Forwarded-For"].FirstOrDefault();
        return string.IsNullOrWhiteSpace(forwardedFor)
            ? null
            : forwardedFor.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries).FirstOrDefault();
    }
}

public record ChatMessageRequest
{
    public Guid PostId { get; init; }
    public string Message { get; init; } = string.Empty;
    public string? SessionId { get; init; }
    public string? OperationId { get; init; }
    public List<ChatHistoryItemRequest>? ConversationHistory { get; init; }
    public string? Language { get; init; }
    public bool EnableWebSearch { get; init; }
    public string? ClientFingerprint { get; init; }
    public string? TurnstileToken { get; init; }
}

public record ChatHistoryItemRequest
{
    public string Role { get; init; } = string.Empty;
    public string Content { get; init; } = string.Empty;
}
