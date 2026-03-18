using System.Security.Claims;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Server.Application.Common.Constants;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AiFeature.Commands.AnalyzeSentimentCommand;
using BlogApp.Server.Application.Features.AiFeature.Commands.CalculateReadingTimeCommand;
using BlogApp.Server.Application.Features.AiFeature.Commands.CollectSourcesCommand;
using BlogApp.Server.Application.Features.AiFeature.Commands.ExtractKeywordsCommand;
using BlogApp.Server.Application.Features.AiFeature.Commands.GenerateExcerptCommand;
using BlogApp.Server.Application.Features.AiFeature.Commands.GenerateSeoDescriptionCommand;
using BlogApp.Server.Application.Features.AiFeature.Commands.GenerateTagsCommand;
using BlogApp.Server.Application.Features.AiFeature.Commands.GenerateTitleCommand;
using BlogApp.Server.Application.Features.AiFeature.Commands.GeoOptimizeCommand;
using BlogApp.Server.Application.Features.AiFeature.Commands.ImproveContentCommand;
using BlogApp.Server.Application.Features.AiFeature.Commands.SummarizeCommand;
using MediatR;
using static System.Security.Claims.ClaimTypes;

namespace BlogApp.Server.Api.Endpoints;

public static class AiEndpoints
{
    public static IEndpointRouteBuilder RegisterAiEndpoints(this IEndpointRouteBuilder app)
    {
        var versionedGroup = app.NewVersionedApi("AI");
        var group = versionedGroup.MapGroup("/api/v{version:apiVersion}/ai")
            .HasApiVersion(1.0)
            .WithTags("AI")
            .RequireAuthorization();

        group.MapPost("/generate-title", async (
            GenerateTitleRequest request,
            IMediator mediator,
            IQueueDepthService queueDepthService,
            ClaimsPrincipal user,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            if (!TryGetUserId(user, out var userId, out var unauthorizedResult))
            {
                return unauthorizedResult!;
            }

            if (!IdempotencyEndpointHelper.TryResolveOperationId(httpContext, request.OperationId, out var operationId, out var operationError))
            {
                return operationError!;
            }

            var depthInfo = await queueDepthService.GetQueueDepthAsync(
                MessagingConstants.QueueNames.AiAuthoring, cancellationToken);
            var isBackpressured = depthInfo.Depth > 10 && !depthInfo.IsStale;

            var response = await mediator.Send(new GenerateTitleCommandRequest
            {
                Content = request.Content,
                UserId = userId,
                OperationId = operationId
            }, cancellationToken);

            return BuildAiResult(
                response,
                response.Data,
                () => new GenerateTitleResponse(response.Data.Value!),
                isBackpressured);
        })
        .WithName("GenerateTitle")
        .Produces<ApiResponse<GenerateTitleResponse>>(StatusCodes.Status200OK)
        .Produces(StatusCodes.Status202Accepted)
        .Produces(StatusCodes.Status409Conflict)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized);

        group.MapPost("/generate-excerpt", async (
            GenerateExcerptRequest request,
            IMediator mediator,
            IQueueDepthService queueDepthService,
            ClaimsPrincipal user,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            if (!TryGetUserId(user, out var userId, out var unauthorizedResult))
            {
                return unauthorizedResult!;
            }

            if (!IdempotencyEndpointHelper.TryResolveOperationId(httpContext, request.OperationId, out var operationId, out var operationError))
            {
                return operationError!;
            }

            var depthInfo = await queueDepthService.GetQueueDepthAsync(
                MessagingConstants.QueueNames.AiAuthoring, cancellationToken);
            var isBackpressured = depthInfo.Depth > 10 && !depthInfo.IsStale;

            var response = await mediator.Send(new GenerateExcerptCommandRequest
            {
                Content = request.Content,
                UserId = userId,
                OperationId = operationId
            }, cancellationToken);

            return BuildAiResult(
                response,
                response.Data,
                () => new GenerateExcerptResponse(response.Data.Value!),
                isBackpressured);
        })
        .WithName("GenerateExcerpt")
        .Produces<ApiResponse<GenerateExcerptResponse>>(StatusCodes.Status200OK)
        .Produces(StatusCodes.Status202Accepted)
        .Produces(StatusCodes.Status409Conflict)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized);

        group.MapPost("/generate-tags", async (
            GenerateTagsRequest request,
            IMediator mediator,
            IQueueDepthService queueDepthService,
            ClaimsPrincipal user,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            if (!TryGetUserId(user, out var userId, out var unauthorizedResult))
            {
                return unauthorizedResult!;
            }

            if (!IdempotencyEndpointHelper.TryResolveOperationId(httpContext, request.OperationId, out var operationId, out var operationError))
            {
                return operationError!;
            }

            var depthInfo = await queueDepthService.GetQueueDepthAsync(
                MessagingConstants.QueueNames.AiAuthoring, cancellationToken);
            var isBackpressured = depthInfo.Depth > 10 && !depthInfo.IsStale;

            var response = await mediator.Send(new GenerateTagsCommandRequest
            {
                Content = request.Content,
                UserId = userId,
                OperationId = operationId
            }, cancellationToken);

            return BuildAiResult(
                response,
                response.Data,
                () => new GenerateTagsResponse(response.Data.Value!),
                isBackpressured);
        })
        .WithName("GenerateTags")
        .Produces<ApiResponse<GenerateTagsResponse>>(StatusCodes.Status200OK)
        .Produces(StatusCodes.Status202Accepted)
        .Produces(StatusCodes.Status409Conflict)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized);

        group.MapPost("/generate-seo", async (
            GenerateSeoRequest request,
            IMediator mediator,
            IQueueDepthService queueDepthService,
            ClaimsPrincipal user,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            if (!TryGetUserId(user, out var userId, out var unauthorizedResult))
            {
                return unauthorizedResult!;
            }

            if (!IdempotencyEndpointHelper.TryResolveOperationId(httpContext, request.OperationId, out var operationId, out var operationError))
            {
                return operationError!;
            }

            var depthInfo = await queueDepthService.GetQueueDepthAsync(
                MessagingConstants.QueueNames.AiAuthoring, cancellationToken);
            var isBackpressured = depthInfo.Depth > 10 && !depthInfo.IsStale;

            var response = await mediator.Send(new GenerateSeoDescriptionCommandRequest
            {
                Content = request.Content,
                UserId = userId,
                OperationId = operationId
            }, cancellationToken);

            return BuildAiResult(
                response,
                response.Data,
                () => new GenerateSeoResponse(response.Data.Value!),
                isBackpressured);
        })
        .WithName("GenerateSeoDescription")
        .Produces<ApiResponse<GenerateSeoResponse>>(StatusCodes.Status200OK)
        .Produces(StatusCodes.Status202Accepted)
        .Produces(StatusCodes.Status409Conflict)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized);

        group.MapPost("/improve-content", async (
            ImproveContentRequest request,
            IMediator mediator,
            IQueueDepthService queueDepthService,
            ClaimsPrincipal user,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            if (!TryGetUserId(user, out var userId, out var unauthorizedResult))
            {
                return unauthorizedResult!;
            }

            if (!IdempotencyEndpointHelper.TryResolveOperationId(httpContext, request.OperationId, out var operationId, out var operationError))
            {
                return operationError!;
            }

            var depthInfo = await queueDepthService.GetQueueDepthAsync(
                MessagingConstants.QueueNames.AiAuthoring, cancellationToken);
            var isBackpressured = depthInfo.Depth > 10 && !depthInfo.IsStale;

            var response = await mediator.Send(new ImproveContentCommandRequest
            {
                Content = request.Content,
                UserId = userId,
                OperationId = operationId
            }, cancellationToken);

            return BuildAiResult(
                response,
                response.Data,
                () => new ImproveContentResponse(response.Data.Value!),
                isBackpressured);
        })
        .WithName("ImproveContent")
        .Produces<ApiResponse<ImproveContentResponse>>(StatusCodes.Status200OK)
        .Produces(StatusCodes.Status202Accepted)
        .Produces(StatusCodes.Status409Conflict)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized);

        group.MapPost("/summarize", async (
            SummarizeRequest request,
            IMediator mediator,
            ClaimsPrincipal user,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            if (!TryGetUserId(user, out var userId, out var unauthorizedResult))
            {
                return unauthorizedResult!;
            }

            if (!IdempotencyEndpointHelper.TryResolveOperationId(httpContext, request.OperationId, out var operationId, out var operationError))
            {
                return operationError!;
            }

            var response = await mediator.Send(new SummarizeCommandRequest
            {
                Content = request.Content,
                UserId = userId,
                OperationId = operationId,
                MaxSentences = request.MaxSentences,
                Language = request.Language ?? "tr"
            }, cancellationToken);

            return BuildAiResult(
                response,
                response.Data,
                () => new SummarizeResponse(response.Data.Value!));
        })
        .WithName("Summarize")
        .Produces<ApiResponse<SummarizeResponse>>(StatusCodes.Status200OK)
        .Produces(StatusCodes.Status202Accepted)
        .Produces(StatusCodes.Status409Conflict)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized);

        group.MapPost("/keywords", async (
            KeywordsRequest request,
            IMediator mediator,
            ClaimsPrincipal user,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            if (!TryGetUserId(user, out var userId, out var unauthorizedResult))
            {
                return unauthorizedResult!;
            }

            if (!IdempotencyEndpointHelper.TryResolveOperationId(httpContext, request.OperationId, out var operationId, out var operationError))
            {
                return operationError!;
            }

            var response = await mediator.Send(new ExtractKeywordsCommandRequest
            {
                Content = request.Content,
                UserId = userId,
                OperationId = operationId,
                MaxKeywords = request.MaxKeywords,
                Language = request.Language ?? "tr"
            }, cancellationToken);

            return BuildAiResult(
                response,
                response.Data,
                () => new KeywordsResponse(response.Data.Value!));
        })
        .WithName("ExtractKeywords")
        .Produces<ApiResponse<KeywordsResponse>>(StatusCodes.Status200OK)
        .Produces(StatusCodes.Status202Accepted)
        .Produces(StatusCodes.Status409Conflict)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized);

        group.MapPost("/sentiment", async (
            SentimentRequest request,
            IMediator mediator,
            ClaimsPrincipal user,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            if (!TryGetUserId(user, out var userId, out var unauthorizedResult))
            {
                return unauthorizedResult!;
            }

            if (!IdempotencyEndpointHelper.TryResolveOperationId(httpContext, request.OperationId, out var operationId, out var operationError))
            {
                return operationError!;
            }

            var response = await mediator.Send(new AnalyzeSentimentCommandRequest
            {
                Content = request.Content,
                UserId = userId,
                OperationId = operationId,
                Language = request.Language ?? "tr"
            }, cancellationToken);

            return BuildAiResult(
                response,
                response.Data,
                () => new SentimentResponse(response.Data.Value!.Sentiment, response.Data.Value.Confidence));
        })
        .WithName("AnalyzeSentiment")
        .Produces<ApiResponse<SentimentResponse>>(StatusCodes.Status200OK)
        .Produces(StatusCodes.Status202Accepted)
        .Produces(StatusCodes.Status409Conflict)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized);

        group.MapPost("/reading-time", async (
            ReadingTimeRequest request,
            IMediator mediator,
            ClaimsPrincipal user,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            if (!TryGetUserId(user, out var userId, out var unauthorizedResult))
            {
                return unauthorizedResult!;
            }

            if (!IdempotencyEndpointHelper.TryResolveOperationId(httpContext, request.OperationId, out var operationId, out var operationError))
            {
                return operationError!;
            }

            var response = await mediator.Send(new CalculateReadingTimeCommandRequest
            {
                Content = request.Content,
                UserId = userId,
                OperationId = operationId
            }, cancellationToken);

            return BuildAiResult(
                response,
                response.Data,
                () => new ReadingTimeResponse(response.Data.Value!.ReadingTimeMinutes, response.Data.Value.WordCount));
        })
        .WithName("CalculateReadingTime")
        .Produces<ApiResponse<ReadingTimeResponse>>(StatusCodes.Status200OK)
        .Produces(StatusCodes.Status202Accepted)
        .Produces(StatusCodes.Status409Conflict)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized);

        group.MapPost("/geo-optimize", async (
            GeoOptimizeRequest request,
            IMediator mediator,
            ClaimsPrincipal user,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            if (!TryGetUserId(user, out var userId, out var unauthorizedResult))
            {
                return unauthorizedResult!;
            }

            if (!IdempotencyEndpointHelper.TryResolveOperationId(httpContext, request.OperationId, out var operationId, out var operationError))
            {
                return operationError!;
            }

            var response = await mediator.Send(new GeoOptimizeCommandRequest
            {
                Content = request.Content,
                UserId = userId,
                OperationId = operationId,
                TargetRegion = request.TargetRegion ?? "TR",
                Language = request.Language ?? "tr"
            }, cancellationToken);

            return BuildAiResult(
                response,
                response.Data,
                () => new GeoOptimizeResponse(
                    response.Data.Value!.TargetRegion,
                    response.Data.Value.LocalizedTitle,
                    response.Data.Value.LocalizedSummary,
                    response.Data.Value.LocalizedKeywords,
                    response.Data.Value.CulturalNotes));
        })
        .WithName("GeoOptimize")
        .Produces<ApiResponse<GeoOptimizeResponse>>(StatusCodes.Status200OK)
        .Produces(StatusCodes.Status202Accepted)
        .Produces(StatusCodes.Status409Conflict)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized);

        group.MapPost("/collect-sources", async (
            CollectSourcesRequest request,
            IMediator mediator,
            ClaimsPrincipal user,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            if (!TryGetUserId(user, out var userId, out var unauthorizedResult))
            {
                return unauthorizedResult!;
            }

            if (!IdempotencyEndpointHelper.TryResolveOperationId(httpContext, request.OperationId, out var operationId, out var operationError))
            {
                return operationError!;
            }

            var response = await mediator.Send(new CollectSourcesCommandRequest
            {
                Query = request.Query,
                UserId = userId,
                OperationId = operationId,
                MaxSources = request.MaxSources,
                Language = request.Language ?? "tr"
            }, cancellationToken);

            return BuildAiResult(
                response,
                response.Data,
                () => new CollectSourcesResponse(response.Data.Value!
                    .Select(s => new WebSourceDto(s.Title, s.Url, s.Snippet))
                    .ToArray()));
        })
        .WithName("CollectSources")
        .Produces<ApiResponse<CollectSourcesResponse>>(StatusCodes.Status200OK)
        .Produces(StatusCodes.Status202Accepted)
        .Produces(StatusCodes.Status409Conflict)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized);

        return app;
    }

    private static bool TryGetUserId(ClaimsPrincipal user, out Guid userId, out IResult? unauthorizedResult)
    {
        userId = Guid.Empty;
        var userIdClaim = user.FindFirst(NameIdentifier)?.Value;
        if (string.IsNullOrEmpty(userIdClaim) || !Guid.TryParse(userIdClaim, out userId))
        {
            unauthorizedResult = Results.Json(
                ApiResponse<object>.FailureResult("Authentication required or invalid user ID"),
                statusCode: StatusCodes.Status401Unauthorized);
            return false;
        }

        unauthorizedResult = null;
        return true;
    }

    private static IResult BuildAiResult<TResult, TPayload>(
        IAiOperationResponse metadata,
        Result<TResult> result,
        Func<TPayload> successFactory,
        bool isBackpressured = false)
    {
        if (metadata.IsProcessing)
        {
            return IdempotencyEndpointHelper.BuildProcessingAccepted(
                metadata.OperationId,
                metadata.CorrelationId,
                metadata.ErrorMessage ?? "AI request is still processing.");
        }

        if (string.Equals(metadata.ErrorCode, "operation_conflict", StringComparison.Ordinal))
        {
            return IdempotencyEndpointHelper.BuildConflict(
                metadata.ErrorMessage ?? "The same operationId was used with a different payload.");
        }

        if (string.Equals(metadata.ErrorCode, AsyncOperationErrorCodes.AsyncDispatchUnavailable, StringComparison.Ordinal))
        {
            return Results.Json(
                ApiResponse<TPayload>.FailureResult(metadata.ErrorMessage ?? "AI operations are temporarily unavailable."),
                statusCode: StatusCodes.Status503ServiceUnavailable);
        }

        if (!result.IsSuccess)
        {
            return Results.BadRequest(ApiResponse<TPayload>.FailureResult(result.Error ?? metadata.ErrorMessage ?? "AI request failed"));
        }

        if (isBackpressured)
        {
            return Results.Ok(new
            {
                success = true,
                data = successFactory(),
                isBackpressured = true,
                message = "AI is currently under heavy load, response times may be longer than usual."
            });
        }

        return Results.Ok(ApiResponse<TPayload>.SuccessResult(successFactory()));
    }
}

public record GenerateTitleRequest(string Content, string? OperationId = null);
public record GenerateExcerptRequest(string Content, string? OperationId = null);
public record GenerateTagsRequest(string Content, string? OperationId = null);
public record GenerateSeoRequest(string Content, string? OperationId = null);
public record ImproveContentRequest(string Content, string? OperationId = null);
public record SummarizeRequest(string Content, int MaxSentences = 5, string? Language = null, string? OperationId = null);
public record KeywordsRequest(string Content, int MaxKeywords = 10, string? Language = null, string? OperationId = null);
public record SentimentRequest(string Content, string? Language = null, string? OperationId = null);
public record ReadingTimeRequest(string Content, string? OperationId = null);
public record GeoOptimizeRequest(string Content, string? TargetRegion = null, string? Language = null, string? OperationId = null);
public record CollectSourcesRequest(string Query, int MaxSources = 5, string? Language = null, string? OperationId = null);

public record GenerateTitleResponse(string Title);
public record GenerateExcerptResponse(string Excerpt);
public record GenerateTagsResponse(string[] Tags);
public record GenerateSeoResponse(string Description);
public record ImproveContentResponse(string Content);
public record SummarizeResponse(string Summary);
public record KeywordsResponse(string[] Keywords);
public record SentimentResponse(string Sentiment, double Confidence);
public record ReadingTimeResponse(int ReadingTimeMinutes, int WordCount);
public record GeoOptimizeResponse(string TargetRegion, string LocalizedTitle, string LocalizedSummary, string[] LocalizedKeywords, string CulturalNotes);
public record CollectSourcesResponse(WebSourceDto[] Sources);
public record WebSourceDto(string Title, string Url, string Snippet);


