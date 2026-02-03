using System.Security.Claims;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.Server.Application.Common.Events;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Commands.CreatePostCommand;
using BlogApp.Server.Application.Features.PostFeature.Commands.DeletePostCommand;
using BlogApp.Server.Application.Features.PostFeature.Commands.GenerateAiSummaryCommand;
using BlogApp.Server.Application.Features.PostFeature.Commands.PublishPostCommand;
using BlogApp.Server.Application.Features.PostFeature.Commands.SaveDraftCommand;
using BlogApp.Server.Application.Features.PostFeature.Commands.UpdateAiAnalysisCommand;
using BlogApp.Server.Application.Features.PostFeature.Commands.UpdatePostCommand;
using BlogApp.Server.Application.Features.PostFeature.DTOs;
using BlogApp.Server.Application.Features.PostFeature.Queries.GetMyPostsQuery;
using BlogApp.Server.Application.Features.PostFeature.Queries.GetPostByIdQuery;
using BlogApp.Server.Application.Features.PostFeature.Queries.GetPostBySlugQuery;
using BlogApp.Server.Application.Features.PostFeature.Queries.GetPostsListQuery;
using BlogApp.Server.Domain.Enums;
using MediatR;

namespace BlogApp.Server.Api.Endpoints;

public static class PostsEndpoints
{
    public static IEndpointRouteBuilder RegisterPostsEndpoints(this IEndpointRouteBuilder app)
    {
        var versionedGroup = app.NewVersionedApi("Posts");
        var group = versionedGroup.MapGroup("/api/v{version:apiVersion}/posts")
            .HasApiVersion(1.0)
            .WithTags("Posts");

        // GET /api/posts
        group.MapGet("/", async (
            int? pageNumber,
            int? pageSize,
            string? searchTerm,
            Guid? categoryId,
            Guid? tagId,
            Guid? authorId,
            PostStatus? status,
            bool? isFeatured,
            string? sortBy,
            bool? sortDescending,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new GetPostsListQueryRequest
            {
                PageNumber = pageNumber is null or 0 ? 1 : pageNumber.Value,
                PageSize = pageSize is null or 0 ? 10 : pageSize.Value,
                SearchTerm = searchTerm,
                CategoryId = categoryId,
                TagId = tagId,
                AuthorId = authorId,
                Status = status,
                IsFeatured = isFeatured,
                SortBy = string.IsNullOrEmpty(sortBy) ? "CreatedAt" : sortBy,
                SortDescending = sortDescending ?? true
            }, cancellationToken);

            return Results.Ok(ApiResponse<PaginatedList<PostListQueryDto>>.SuccessResult(
                response.Result,
                PaginationMeta.FromPaginatedList(response.Result)));
        })
        .WithName("GetAllPosts")
        .WithDescription("Get paginated list of posts")
        .CacheOutput("PostsList")
        .Produces<ApiResponse<PaginatedList<PostListQueryDto>>>(200);

        // GET /api/posts/featured
        group.MapGet("/featured", async (
            int? pageSize,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new GetPostsListQueryRequest
            {
                PageSize = pageSize is null or 0 ? 5 : pageSize.Value,
                IsFeatured = true,
                Status = PostStatus.Published,
                SortDescending = true
            }, cancellationToken);

            return Results.Ok(ApiResponse<PaginatedList<PostListQueryDto>>.SuccessResult(response.Result));
        })
        .WithName("GetFeaturedPosts")
        .WithDescription("Get featured posts")
        .CacheOutput("PostsList")
        .Produces<ApiResponse<PaginatedList<PostListQueryDto>>>(200);

        // GET /api/posts/drafts
        group.MapGet("/drafts", async (
            int? page,
            int? pageSize,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new GetPostsListQueryRequest
            {
                PageNumber = page is null or 0 ? 1 : page.Value,
                PageSize = pageSize is null or 0 ? 10 : pageSize.Value,
                Status = PostStatus.Draft,
                SortDescending = true
            }, cancellationToken);

            return Results.Ok(ApiResponse<PaginatedList<PostListQueryDto>>.SuccessResult(response.Result));
        })
        .WithName("GetDrafts")
        .WithDescription("Get user's drafts")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .Produces<ApiResponse<PaginatedList<PostListQueryDto>>>(200);

        // GET /api/posts/my
        group.MapGet("/my", async (
            int? page,
            int? pageSize,
            HttpContext context,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var userIdClaim = context.User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (string.IsNullOrEmpty(userIdClaim) || !Guid.TryParse(userIdClaim, out var userId))
                return Results.Unauthorized();

            var response = await mediator.Send(new GetMyPostsQueryRequest
            {
                UserId = userId,
                PageNumber = page is null or 0 ? 1 : page.Value,
                PageSize = pageSize is null or 0 ? 10 : pageSize.Value
            }, cancellationToken);

            return Results.Ok(ApiResponse<PaginatedList<PostListQueryDto>>.SuccessResult(
                response.Result,
                PaginationMeta.FromPaginatedList(response.Result)));
        })
        .WithName("GetMyPosts")
        .WithDescription("Get current user's posts")
        .RequireAuthorization()
        .Produces<ApiResponse<PaginatedList<PostListQueryDto>>>(200);

        // GET /api/posts/{id}
        group.MapGet("/{id:guid}", async (
            Guid id,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new GetPostByIdQueryRequest
            {
                Id = id
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));

            return Results.Ok(ApiResponse<PostDetailQueryDto>.SuccessResult(response.Result.Value!));
        })
        .WithName("GetPostById")
        .WithDescription("Get post by ID")
        .Produces<ApiResponse<PostDetailQueryDto>>(200)
        .Produces(404);

        // GET /api/posts/slug/{slug}
        group.MapGet("/slug/{slug}", async (
            string slug,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new GetPostBySlugQueryRequest
            {
                Slug = slug
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));

            return Results.Ok(ApiResponse<PostDetailQueryDto>.SuccessResult(response.Result.Value!));
        })
        .WithName("GetPostBySlug")
        .WithDescription("Get post by slug")
        .CacheOutput("PostDetail")
        .Produces<ApiResponse<PostDetailQueryDto>>(200)
        .Produces(404);

        // POST /api/posts
        group.MapPost("/", async (
            CreatePostCommandDto dto,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new CreatePostCommandRequest
            {
                CreatePostCommandRequestDto = dto
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.BadRequest(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));

            var postResponse = await mediator.Send(new GetPostByIdQueryRequest
            {
                Id = response.Result.Value
            }, cancellationToken);

            // Null safety: Post created but fetch failed - return partial success with ID
            if (!postResponse.Result.IsSuccess || postResponse.Result.Value is null)
            {
                return Results.Problem(
                    detail: $"Post created successfully (ID: {response.Result.Value}) but details could not be fetched. Please fetch manually.",
                    statusCode: StatusCodes.Status207MultiStatus,
                    title: "Partial Success");
            }

            return Results.Created(
                $"/api/posts/{response.Result.Value}",
                ApiResponse<PostDetailQueryDto>.SuccessResult(postResponse.Result.Value, "Post created successfully"));
        })
        .WithName("CreatePost")
        .WithDescription("Create a new post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .Produces<ApiResponse<PostDetailQueryDto>>(201)
        .Produces(400)
        .Produces(401);

        // PUT /api/posts/{id}
        group.MapPut("/{id:guid}", async (
            Guid id,
            UpdatePostCommandDto dto,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            dto.Id = id;

            var response = await mediator.Send(new UpdatePostCommandRequest
            {
                UpdatePostCommandRequestDto = dto
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.BadRequest(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));

            var postResponse = await mediator.Send(new GetPostByIdQueryRequest
            {
                Id = id
            }, cancellationToken);

            // Null safety: Post updated but fetch failed - return partial success with ID
            if (!postResponse.Result.IsSuccess || postResponse.Result.Value is null)
            {
                return Results.Problem(
                    detail: $"Post updated successfully (ID: {id}) but details could not be fetched. Please fetch manually.",
                    statusCode: StatusCodes.Status207MultiStatus,
                    title: "Partial Success");
            }

            return Results.Ok(ApiResponse<PostDetailQueryDto>.SuccessResult(postResponse.Result.Value, "Post updated successfully"));
        })
        .WithName("UpdatePost")
        .WithDescription("Update an existing post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .Produces<ApiResponse<PostDetailQueryDto>>(200)
        .Produces(400)
        .Produces(404);

        // DELETE /api/posts/{id}
        group.MapDelete("/{id:guid}", async (
            Guid id,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new DeletePostCommandRequest
            {
                Id = id
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<object>.FailureResult(response.Result.Error!));

            return Results.NoContent();
        })
        .WithName("DeletePost")
        .WithDescription("Delete a post (soft delete)")
        .RequireAuthorization(policy => policy.RequireRole("Admin"))
        .Produces(204)
        .Produces(404);

        // POST /api/posts/{id}/publish
        group.MapPost("/{id:guid}/publish", async (
            Guid id,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new PublishPostCommandRequest
            {
                Id = id
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));

            var postResponse = await mediator.Send(new GetPostByIdQueryRequest
            {
                Id = id
            }, cancellationToken);

            // Null safety: Post published but fetch failed - return partial success with ID
            if (!postResponse.Result.IsSuccess || postResponse.Result.Value is null)
            {
                return Results.Problem(
                    detail: $"Post published successfully (ID: {id}) but details could not be fetched. Please fetch manually.",
                    statusCode: StatusCodes.Status207MultiStatus,
                    title: "Partial Success");
            }

            return Results.Ok(ApiResponse<PostDetailQueryDto>.SuccessResult(postResponse.Result.Value, "Post published successfully"));
        })
        .WithName("PublishPost")
        .WithDescription("Publish a post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor"))
        .Produces<ApiResponse<PostDetailQueryDto>>(200)
        .Produces(404);

        // POST /api/posts/{id}/unpublish
        group.MapPost("/{id:guid}/unpublish", async (
            Guid id,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new UnpublishPostCommandRequest
            {
                Id = id
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));

            var postResponse = await mediator.Send(new GetPostByIdQueryRequest
            {
                Id = id
            }, cancellationToken);

            // Null safety: Post unpublished but fetch failed - return partial success with ID
            if (!postResponse.Result.IsSuccess || postResponse.Result.Value is null)
            {
                return Results.Problem(
                    detail: $"Post unpublished successfully (ID: {id}) but details could not be fetched. Please fetch manually.",
                    statusCode: StatusCodes.Status207MultiStatus,
                    title: "Partial Success");
            }

            return Results.Ok(ApiResponse<PostDetailQueryDto>.SuccessResult(postResponse.Result.Value, "Post unpublished successfully"));
        })
        .WithName("UnpublishPost")
        .WithDescription("Unpublish a post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor"))
        .Produces<ApiResponse<PostDetailQueryDto>>(200)
        .Produces(404);

        // POST /api/posts/{id}/archive
        group.MapPost("/{id:guid}/archive", async (
            Guid id,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new UnpublishPostCommandRequest
            {
                Id = id
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));

            var postResponse = await mediator.Send(new GetPostByIdQueryRequest
            {
                Id = id
            }, cancellationToken);

            // Null safety: Post archived but fetch failed - return partial success with ID
            if (!postResponse.Result.IsSuccess || postResponse.Result.Value is null)
            {
                return Results.Problem(
                    detail: $"Post archived successfully (ID: {id}) but details could not be fetched. Please fetch manually.",
                    statusCode: StatusCodes.Status207MultiStatus,
                    title: "Partial Success");
            }

            return Results.Ok(ApiResponse<PostDetailQueryDto>.SuccessResult(postResponse.Result.Value, "Post archived successfully"));
        })
        .WithName("ArchivePost")
        .WithDescription("Archive a post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor"))
        .Produces<ApiResponse<PostDetailQueryDto>>(200)
        .Produces(404);

        // POST /api/posts/draft
        group.MapPost("/draft", async (
            SaveDraftCommandDto dto,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new SaveDraftCommandRequest
            {
                SaveDraftCommandRequestDto = dto
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.BadRequest(ApiResponse<Guid>.FailureResult(response.Result.Error!));

            return Results.Ok(ApiResponse<Guid>.SuccessResult(response.Result.Value, "Draft saved"));
        })
        .WithName("SaveDraft")
        .WithDescription("Save draft (auto-save endpoint)")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .Produces<ApiResponse<Guid>>(200)
        .Produces(400);

        // PUT /api/posts/draft
        group.MapPut("/draft", async (
            SaveDraftCommandDto dto,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new SaveDraftCommandRequest
            {
                SaveDraftCommandRequestDto = dto
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.BadRequest(ApiResponse<Guid>.FailureResult(response.Result.Error!));

            return Results.Ok(ApiResponse<Guid>.SuccessResult(response.Result.Value, "Draft saved"));
        })
        .WithName("UpdateDraft")
        .WithDescription("Update draft (auto-save endpoint)")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .Produces<ApiResponse<Guid>>(200)
        .Produces(400);

        // PATCH /api/posts/{id}/ai-analysis
        // AI Agent Service tarafından çağrılır - makale AI analiz sonuçlarını günceller
        group.MapPatch("/{id:guid}/ai-analysis", async (
            Guid id,
            UpdateAiAnalysisDto dto,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new UpdateAiAnalysisCommandRequest
            {
                PostId = id,
                AiSummary = dto.AiSummary,
                AiKeywords = dto.AiKeywords,
                AiEstimatedReadingTime = dto.EstimatedReadingTime,
                AiSeoDescription = dto.AiSeoDescription,
                AiGeoOptimization = dto.AiGeoOptimization
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<object>.FailureResult(response.Result.Error!));

            return Results.NoContent();
        })
        .WithName("UpdateAiAnalysis")
        .WithDescription("Update AI analysis results for a post (called by AI Agent Service)")
        .Produces(204)
        .Produces(404);

        // POST /api/posts/{id}/generate-ai-summary
        // Kullanıcılar ve Admin için - Makalenin AI özetini oluşturur
        group.MapPost("/{id:guid}/generate-ai-summary", async (
            Guid id,
            int? maxSentences,
            string? language,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new GenerateAiSummaryCommandRequest
            {
                PostId = id,
                MaxSentences = maxSentences ?? 3,
                Language = language ?? "tr"
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.BadRequest(ApiResponse<GenerateAiSummaryResponseDto>.FailureResult(response.Result.Error!));

            return Results.Ok(ApiResponse<GenerateAiSummaryResponseDto>.SuccessResult(
                new GenerateAiSummaryResponseDto
                {
                    Summary = response.Summary,
                    WordCount = response.WordCount
                },
                "AI summary generated successfully"));
        })
        .WithName("GenerateAiSummary")
        .WithDescription("Generate AI summary for a post (available for both users and admin)")
        .Produces<ApiResponse<GenerateAiSummaryResponseDto>>(200)
        .Produces(400)
        .Produces(404);

        // POST /api/posts/{id}/request-ai-analysis
        // Event-driven AI analysis request - publishes to RabbitMQ
        // AI Agent listens and processes, then publishes result back
        group.MapPost("/{id:guid}/request-ai-analysis", async (
            Guid id,
            RequestAiAnalysisDto? dto,
            IEventBus eventBus,
            IUnitOfWork unitOfWork,
            ILoggerFactory loggerFactory,
            CancellationToken cancellationToken) =>
        {
            var logger = loggerFactory.CreateLogger("PostsEndpoints");

            // Get the post
            var post = await unitOfWork.PostsRead.GetByIdAsync(id, cancellationToken);
            if (post is null)
                return Results.NotFound(ApiResponse<object>.FailureResult("Post not found"));

            // Generate correlation ID for tracking
            var correlationId = Guid.NewGuid().ToString();

            // Publish analysis request to RabbitMQ
            var analysisEvent = new ArticleAnalysisRequestedEvent
            {
                CorrelationId = correlationId,
                Payload = new ArticlePayload
                {
                    ArticleId = post.Id,
                    Title = post.Title,
                    Content = post.Content,
                    AuthorId = post.AuthorId,
                    Language = dto?.Language ?? "tr",
                    TargetRegion = dto?.TargetRegion ?? "TR"
                }
            };

            await eventBus.PublishAsync(
                analysisEvent,
                MessagingConstants.RoutingKeys.AiAnalysisRequested,
                cancellationToken);

            logger.LogInformation(
                "Published AI analysis request for post {PostId} with CorrelationId {CorrelationId}",
                id,
                correlationId);

            return Results.Accepted(
                value: ApiResponse<RequestAiAnalysisResponseDto>.SuccessResult(
                    new RequestAiAnalysisResponseDto
                    {
                        PostId = id,
                        CorrelationId = correlationId,
                        Message = "AI analysis request submitted. Results will be delivered via SignalR."
                    },
                    "AI analysis request accepted"));
        })
        .WithName("RequestAiAnalysis")
        .WithDescription("Request AI analysis for a post (event-driven, results via SignalR)")
        .Produces<ApiResponse<RequestAiAnalysisResponseDto>>(202)
        .Produces(404);

        return app;
    }
}

/// <summary>
/// DTO for AI analysis update request
/// </summary>
public record UpdateAiAnalysisDto
{
    public string? AiSummary { get; init; }
    public string? AiKeywords { get; init; }
    public int? EstimatedReadingTime { get; init; }
    public string? AiSeoDescription { get; init; }
    public string? AiGeoOptimization { get; init; }
}

/// <summary>
/// DTO for AI summary generation response
/// </summary>
public record GenerateAiSummaryResponseDto
{
    public string? Summary { get; init; }
    public int WordCount { get; init; }
}

/// <summary>
/// DTO for AI analysis request
/// </summary>
public record RequestAiAnalysisDto
{
    /// <summary>
    /// Content language (default: tr)
    /// </summary>
    public string? Language { get; init; }

    /// <summary>
    /// Target region for GEO optimization (default: TR)
    /// </summary>
    public string? TargetRegion { get; init; }
}

/// <summary>
/// DTO for AI analysis request response
/// </summary>
public record RequestAiAnalysisResponseDto
{
    /// <summary>
    /// Post ID that analysis was requested for
    /// </summary>
    public Guid PostId { get; init; }

    /// <summary>
    /// Correlation ID for tracking the request
    /// </summary>
    public string CorrelationId { get; init; } = string.Empty;

    /// <summary>
    /// Status message
    /// </summary>
    public string Message { get; init; } = string.Empty;
}

