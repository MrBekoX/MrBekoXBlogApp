using System.Security.Claims;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.Server.Api.Extensions;
using BlogApp.Server.Api.Filters;
using BlogApp.Server.Application.Common.Constants;
using BlogApp.Server.Application.Common.Events;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Common.Security;
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
            HttpContext httpContext,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var subject = httpContext.User.ToPostAuthorizationSubject();
            var effectiveAuthorId = authorId;
            var effectiveStatus = PostStatus.Published;

            if (status is null || status == PostStatus.Published)
            {
                effectiveStatus = status ?? PostStatus.Published;
            }
            else if (subject.IsInRole("Admin") || subject.IsInRole("Editor"))
            {
                effectiveStatus = status.Value;
            }
            else if (subject.IsInRole("Author") && subject.UserId.HasValue)
            {
                effectiveStatus = status.Value;
                effectiveAuthorId = subject.UserId.Value;
            }

            var response = await mediator.Send(new GetPostsListQueryRequest
            {
                PageNumber = pageNumber is null or 0 ? 1 : pageNumber.Value,
                PageSize = pageSize is null or 0 ? 10 : pageSize.Value,
                SearchTerm = searchTerm,
                CategoryId = categoryId,
                TagId = tagId,
                AuthorId = effectiveAuthorId,
                Status = effectiveStatus,
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

        group.MapGet("/drafts", async (
            int? page,
            int? pageSize,
            Guid? authorId,
            HttpContext context,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var subject = context.User.ToPostAuthorizationSubject();
            if (!subject.IsAuthenticated)
            {
                return Results.Json(
                    ApiResponse<PaginatedList<PostListQueryDto>>.FailureResult("User not authenticated."),
                    statusCode: StatusCodes.Status401Unauthorized);
            }

            Guid? effectiveAuthorId = authorId;
            if (subject.IsInRole("Author"))
            {
                effectiveAuthorId = subject.UserId;
            }

            var response = await mediator.Send(new GetPostsListQueryRequest
            {
                PageNumber = page is null or 0 ? 1 : page.Value,
                PageSize = pageSize is null or 0 ? 10 : pageSize.Value,
                Status = PostStatus.Draft,
                AuthorId = effectiveAuthorId,
                SortDescending = true
            }, cancellationToken);

            return Results.Ok(ApiResponse<PaginatedList<PostListQueryDto>>.SuccessResult(response.Result));
        })
        .WithName("GetDrafts")
        .WithDescription("Get current user's drafts")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .Produces<ApiResponse<PaginatedList<PostListQueryDto>>>(200);

        group.MapGet("/my", async (
            int? page,
            int? pageSize,
            HttpContext context,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var userIdClaim = context.User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (string.IsNullOrEmpty(userIdClaim) || !Guid.TryParse(userIdClaim, out var userId))
            {
                return Results.Json(
                    ApiResponse<PaginatedList<PostListQueryDto>>.FailureResult("User not authenticated or invalid user ID"),
                    statusCode: StatusCodes.Status401Unauthorized);
            }

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

        group.MapGet("/{id:guid}", async (
            Guid id,
            HttpContext httpContext,
            IPostAuthorizationService postAuthorizationService,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var decision = await postAuthorizationService.AuthorizeAsync(
                id,
                httpContext.User.ToPostAuthorizationSubject(),
                PostAuthorizationAction.ViewPublished,
                cancellationToken);

            if (!decision.Exists || !decision.IsAuthorized)
            {
                return Results.NotFound(ApiResponse<PostDetailQueryDto>.FailureResult("Post not found"));
            }

            var response = await mediator.Send(new GetPostByIdQueryRequest
            {
                Id = id,
                RequirePublishedStatus = decision.Status == PostStatus.Published
            }, cancellationToken);

            if (!response.Result.IsSuccess)
            {
                return Results.NotFound(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));
            }

            return Results.Ok(ApiResponse<PostDetailQueryDto>.SuccessResult(response.Result.Value!));
        })
        .WithName("GetPostById")
        .WithDescription("Get post by ID")
        .Produces<ApiResponse<PostDetailQueryDto>>(200)
        .Produces(404);

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

        group.MapPost("/", async (
            CreatePostCommandDto dto,
            IMediator mediator,
            HttpContext httpContext,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            CancellationToken cancellationToken) =>
        {
            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                httpContext, "CreatePost", dto, unitOfWork, idempotencyService, currentUserService, cancellationToken,
                requireIdempotencyKey: true);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            var response = await mediator.Send(new CreatePostCommandRequest
            {
                CreatePostCommandRequestDto = dto
            }, cancellationToken);

            if (!response.Result.IsSuccess)
            {
                await scope.FailAndCommitAsync(
                    "validation_error", response.Result.Error!, idempotencyService, cancellationToken);
                return Results.BadRequest(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));
            }

            var postResponse = await mediator.Send(new GetPostByIdQueryRequest
            {
                Id = response.Result.Value,
                RequirePublishedStatus = false
            }, cancellationToken);

            if (!postResponse.Result.IsSuccess || postResponse.Result.Value is null)
            {
                var partialResponse = BuildPostPartialSuccessResponse(response.Result.Value, "created");
                await scope.CompleteAndCommitAsync(
                    StatusCodes.Status207MultiStatus, partialResponse, idempotencyService, cancellationToken);
                return Results.Json(partialResponse, statusCode: StatusCodes.Status207MultiStatus);
            }

            var result = ApiResponse<PostDetailQueryDto>.SuccessResult(postResponse.Result.Value, "Post created successfully");
            await scope.CompleteAndCommitAsync(
                StatusCodes.Status201Created, result, idempotencyService, cancellationToken);

            return Results.Created($"/api/posts/{response.Result.Value}", result);
        })
        .WithName("CreatePost")
        .WithDescription("Create a new post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .Produces<ApiResponse<PostDetailQueryDto>>(201)
        .Produces(400)
        .Produces(401)
        .Produces(StatusCodes.Status409Conflict);

        group.MapPut("/{id:guid}", async (
            Guid id,
            UpdatePostCommandDto dto,
            IMediator mediator,
            HttpContext httpContext,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            CancellationToken cancellationToken) =>
        {
            dto.Id = id;

            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                httpContext, "UpdatePost", dto, unitOfWork, idempotencyService, currentUserService, cancellationToken,
                requireIdempotencyKey: true);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            var response = await mediator.Send(new UpdatePostCommandRequest
            {
                UpdatePostCommandRequestDto = dto
            }, cancellationToken);

            if (!response.Result.IsSuccess)
            {
                await scope.FailAndCommitAsync(
                    "validation_error", response.Result.Error!, idempotencyService, cancellationToken);
                return Results.BadRequest(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));
            }

            var postResponse = await mediator.Send(new GetPostByIdQueryRequest
            {
                Id = id,
                RequirePublishedStatus = false
            }, cancellationToken);

            if (!postResponse.Result.IsSuccess || postResponse.Result.Value is null)
            {
                var partialResponse = BuildPostPartialSuccessResponse(id, "updated");
                await scope.CompleteAndCommitAsync(
                    StatusCodes.Status207MultiStatus, partialResponse, idempotencyService, cancellationToken);
                return Results.Json(partialResponse, statusCode: StatusCodes.Status207MultiStatus);
            }

            var result = ApiResponse<PostDetailQueryDto>.SuccessResult(postResponse.Result.Value, "Post updated successfully");
            await scope.CompleteAndCommitAsync(
                StatusCodes.Status200OK, result, idempotencyService, cancellationToken);

            return Results.Ok(result);
        })
        .WithName("UpdatePost")
        .WithDescription("Update an existing post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .Produces<ApiResponse<PostDetailQueryDto>>(200)
        .Produces(400)
        .Produces(404)
        .Produces(StatusCodes.Status409Conflict);

        group.MapDelete("/{id:guid}", async (
            Guid id,
            IMediator mediator,
            HttpContext httpContext,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            CancellationToken cancellationToken) =>
        {
            var requestPayload = new { Id = id };
            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                httpContext, "DeletePost", requestPayload, unitOfWork, idempotencyService, currentUserService, cancellationToken,
                requireIdempotencyKey: true);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            var response = await mediator.Send(new DeletePostCommandRequest
            {
                Id = id
            }, cancellationToken);

            if (!response.Result.IsSuccess)
            {
                await scope.FailAndCommitAsync(
                    "post_not_found", response.Result.Error!, idempotencyService, cancellationToken);
                return Results.NotFound(ApiResponse<object>.FailureResult(response.Result.Error!));
            }

            var result = ApiResponse<object>.SuccessResult(new { postId = id }, "Post deleted successfully");
            await scope.CompleteAndCommitAsync(
                StatusCodes.Status204NoContent, result, idempotencyService, cancellationToken);

            return Results.NoContent();
        })
        .WithName("DeletePost")
        .WithDescription("Delete a post (soft delete)")
        .RequireAuthorization(policy => policy.RequireRole("Admin"))
        .Produces(204)
        .Produces(404);

        group.MapPost("/{id:guid}/publish", async (
            Guid id,
            IMediator mediator,
            IQueueDepthService queueDepthService,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            if (!IdempotencyEndpointHelper.TryResolveOperationId(httpContext, null, out var operationId, out var operationError))
            {
                return operationError!;
            }

            var response = await mediator.Send(new PublishPostCommandRequest
            {
                Id = id,
                OperationId = operationId
            }, cancellationToken);

            if (response.IsProcessing)
            {
                return IdempotencyEndpointHelper.BuildProcessingAccepted(
                    response.OperationId,
                    response.CorrelationId,
                    response.ErrorMessage ?? "Publish request is still processing.");
            }

            if (string.Equals(response.ErrorCode, "operation_conflict", StringComparison.Ordinal))
            {
                return IdempotencyEndpointHelper.BuildConflict(
                    response.ErrorMessage ?? "The same operationId was used with a different payload.");
            }

            if (!response.Result.IsSuccess)
            {
                if (string.Equals(response.ErrorCode, AsyncOperationErrorCodes.AsyncDispatchUnavailable, StringComparison.Ordinal))
                {
                    return Results.Json(
                        ApiResponse<PostDetailQueryDto>.FailureResult(response.ErrorMessage ?? "Publishing is temporarily unavailable."),
                        statusCode: StatusCodes.Status503ServiceUnavailable);
                }

                if (string.Equals(response.ErrorCode, "post_not_found", StringComparison.Ordinal))
                {
                    return Results.NotFound(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));
                }

                return Results.BadRequest(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));
            }

            var bgDepth = await queueDepthService.GetQueueDepthAsync(
                MessagingConstants.QueueNames.AiBackground, cancellationToken);
            if (bgDepth.Depth > 20 && !bgDepth.IsStale)
            {
                // Background analysis may be delayed due to queue backpressure.
                // Actual skip would need to be handled in the command handler.
            }

            var postResponse = await mediator.Send(new GetPostByIdQueryRequest
            {
                Id = id,
                RequirePublishedStatus = false
            }, cancellationToken);

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
        .Produces(StatusCodes.Status202Accepted)
        .Produces(StatusCodes.Status409Conflict)
        .Produces(404);

        group.MapPost("/{id:guid}/unpublish", async (
            Guid id,
            IMediator mediator,
            HttpContext httpContext,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            CancellationToken cancellationToken) =>
        {
            var requestPayload = new { Id = id };
            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                httpContext, "UnpublishPost", requestPayload, unitOfWork, idempotencyService, currentUserService, cancellationToken,
                requireIdempotencyKey: true);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            var response = await mediator.Send(new UnpublishPostCommandRequest
            {
                Id = id,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault()?.Trim() ?? string.Empty
            }, cancellationToken);

            if (!response.Result.IsSuccess)
            {
                await scope.FailAndCommitAsync(
                    "post_not_found", response.Result.Error!, idempotencyService, cancellationToken);
                return Results.NotFound(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));
            }

            var postResponse = await mediator.Send(new GetPostByIdQueryRequest
            {
                Id = id,
                RequirePublishedStatus = false
            }, cancellationToken);

            if (!postResponse.Result.IsSuccess || postResponse.Result.Value is null)
            {
                var partialResponse = BuildPostPartialSuccessResponse(id, "unpublished");
                await scope.CompleteAndCommitAsync(
                    StatusCodes.Status207MultiStatus, partialResponse, idempotencyService, cancellationToken);
                return Results.Json(partialResponse, statusCode: StatusCodes.Status207MultiStatus);
            }

            var result = ApiResponse<PostDetailQueryDto>.SuccessResult(postResponse.Result.Value, "Post unpublished successfully");
            await scope.CompleteAndCommitAsync(
                StatusCodes.Status200OK, result, idempotencyService, cancellationToken);

            return Results.Ok(result);
        })
        .WithName("UnpublishPost")
        .WithDescription("Unpublish a post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor"))
        .Produces<ApiResponse<PostDetailQueryDto>>(200)
        .Produces(404);

        group.MapPost("/{id:guid}/archive", async (
            Guid id,
            IMediator mediator,
            HttpContext httpContext,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            CancellationToken cancellationToken) =>
        {
            var requestPayload = new { Id = id };
            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                httpContext, "ArchivePost", requestPayload, unitOfWork, idempotencyService, currentUserService, cancellationToken,
                requireIdempotencyKey: true);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            var response = await mediator.Send(new UnpublishPostCommandRequest
            {
                Id = id,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault()?.Trim() ?? string.Empty
            }, cancellationToken);

            if (!response.Result.IsSuccess)
            {
                await scope.FailAndCommitAsync(
                    "post_not_found", response.Result.Error!, idempotencyService, cancellationToken);
                return Results.NotFound(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));
            }

            var postResponse = await mediator.Send(new GetPostByIdQueryRequest
            {
                Id = id,
                RequirePublishedStatus = false
            }, cancellationToken);

            if (!postResponse.Result.IsSuccess || postResponse.Result.Value is null)
            {
                var partialResponse = BuildPostPartialSuccessResponse(id, "archived");
                await scope.CompleteAndCommitAsync(
                    StatusCodes.Status207MultiStatus, partialResponse, idempotencyService, cancellationToken);
                return Results.Json(partialResponse, statusCode: StatusCodes.Status207MultiStatus);
            }

            var result = ApiResponse<PostDetailQueryDto>.SuccessResult(postResponse.Result.Value, "Post archived successfully");
            await scope.CompleteAndCommitAsync(
                StatusCodes.Status200OK, result, idempotencyService, cancellationToken);

            return Results.Ok(result);
        })
        .WithName("ArchivePost")
        .WithDescription("Archive a post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor"))
        .Produces<ApiResponse<PostDetailQueryDto>>(200)
        .Produces(404);

        group.MapPost("/draft", async (
            SaveDraftCommandDto dto,
            IMediator mediator,
            HttpContext httpContext,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            CancellationToken cancellationToken) =>
        {
            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                httpContext, "SaveDraft", dto, unitOfWork, idempotencyService, currentUserService, cancellationToken);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            var response = await mediator.Send(new SaveDraftCommandRequest
            {
                SaveDraftCommandRequestDto = dto
            }, cancellationToken);

            if (!response.Result.IsSuccess)
            {
                await scope.FailAndCommitAsync(
                    "validation_error", response.Result.Error!, idempotencyService, cancellationToken);
                return Results.BadRequest(ApiResponse<Guid>.FailureResult(response.Result.Error!));
            }

            var result = ApiResponse<Guid>.SuccessResult(response.Result.Value, "Draft saved");
            await scope.CompleteAndCommitAsync(
                StatusCodes.Status200OK, result, idempotencyService, cancellationToken);

            return Results.Ok(result);
        })
        .WithName("SaveDraft")
        .WithDescription("Save draft (auto-save endpoint)")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .Produces<ApiResponse<Guid>>(200)
        .Produces(400);

        group.MapPut("/draft", async (
            SaveDraftCommandDto dto,
            IMediator mediator,
            HttpContext httpContext,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            CancellationToken cancellationToken) =>
        {
            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                httpContext, "UpdateDraft", dto, unitOfWork, idempotencyService, currentUserService, cancellationToken);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            var response = await mediator.Send(new SaveDraftCommandRequest
            {
                SaveDraftCommandRequestDto = dto
            }, cancellationToken);

            if (!response.Result.IsSuccess)
            {
                await scope.FailAndCommitAsync(
                    "validation_error", response.Result.Error!, idempotencyService, cancellationToken);
                return Results.BadRequest(ApiResponse<Guid>.FailureResult(response.Result.Error!));
            }

            var result = ApiResponse<Guid>.SuccessResult(response.Result.Value, "Draft saved");
            await scope.CompleteAndCommitAsync(
                StatusCodes.Status200OK, result, idempotencyService, cancellationToken);

            return Results.Ok(result);
        })
        .WithName("UpdateDraft")
        .WithDescription("Update draft (auto-save endpoint)")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .Produces<ApiResponse<Guid>>(200)
        .Produces(400);

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
        .AddEndpointFilter<InternalServiceAuthorizationFilter>()
        .WithName("UpdateAiAnalysis")
        .WithDescription("Update AI analysis results for a post (called by AI Agent Service)")
        .Produces(204)
        .Produces(404);

        group.MapPost("/{id:guid}/generate-ai-summary", async (
            Guid id,
            int? maxSentences,
            string? language,
            string? operationId,
            HttpContext httpContext,
            IPostAuthorizationService postAuthorizationService,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var decision = await postAuthorizationService.AuthorizeAsync(
                id,
                httpContext.User.ToPostAuthorizationSubject(),
                PostAuthorizationAction.TriggerAi,
                cancellationToken);

            if (!decision.Exists)
            {
                return Results.NotFound(ApiResponse<GenerateAiSummaryResponseDto>.FailureResult("Post not found"));
            }

            if (!decision.IsAuthorized)
            {
                return BuildForbidden("You are not allowed to trigger AI operations for this post.");
            }

            if (!IdempotencyEndpointHelper.TryResolveOperationId(httpContext, operationId, out var resolvedOperationId, out var operationError))
            {
                return operationError!;
            }

            var response = await mediator.Send(new GenerateAiSummaryCommandRequest
            {
                PostId = id,
                MaxSentences = maxSentences ?? 3,
                Language = language ?? "tr",
                OperationId = resolvedOperationId
            }, cancellationToken);

            if (response.IsProcessing)
            {
                return IdempotencyEndpointHelper.BuildProcessingAccepted(
                    response.OperationId,
                    response.CorrelationId,
                    response.Message ?? "AI summary request is still processing.");
            }

            if (string.Equals(response.ErrorCode, "operation_conflict", StringComparison.Ordinal))
            {
                return IdempotencyEndpointHelper.BuildConflict(response.ErrorMessage ?? "The same operationId was used with a different payload.");
            }

            if (!response.Result.IsSuccess)
            {
                if (string.Equals(response.ErrorCode, AsyncOperationErrorCodes.AsyncDispatchUnavailable, StringComparison.Ordinal))
                {
                    return Results.Json(
                        ApiResponse<GenerateAiSummaryResponseDto>.FailureResult(response.ErrorMessage ?? "AI summary generation is temporarily unavailable."),
                        statusCode: StatusCodes.Status503ServiceUnavailable);
                }

                return Results.BadRequest(ApiResponse<GenerateAiSummaryResponseDto>.FailureResult(response.Result.Error ?? response.ErrorMessage ?? "AI summary generation failed."));
            }

            return Results.Ok(ApiResponse<GenerateAiSummaryResponseDto>.SuccessResult(
                new GenerateAiSummaryResponseDto
                {
                    Summary = response.Summary,
                    WordCount = response.WordCount,
                    OperationId = response.OperationId,
                    CorrelationId = response.CorrelationId
                },
                "AI summary generated successfully"));
        })
        .WithName("GenerateAiSummary")
        .WithDescription("Generate AI summary for a post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .Produces<ApiResponse<GenerateAiSummaryResponseDto>>(200)
        .Produces(StatusCodes.Status202Accepted)
        .Produces(StatusCodes.Status409Conflict)
        .Produces(400)
        .Produces(403)
        .Produces(404);

        group.MapPost("/{id:guid}/request-ai-analysis", async (
            Guid id,
            RequestAiAnalysisDto? dto,
            IAsyncOperationDispatcher dispatcher,
            IUnitOfWork unitOfWork,
            IPostAuthorizationService postAuthorizationService,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            var decision = await postAuthorizationService.AuthorizeAsync(
                id,
                httpContext.User.ToPostAuthorizationSubject(),
                PostAuthorizationAction.TriggerAi,
                cancellationToken);

            if (!decision.Exists)
            {
                return Results.NotFound(ApiResponse<object>.FailureResult("Post not found"));
            }

            if (!decision.IsAuthorized)
            {
                return BuildForbidden("You are not allowed to trigger AI operations for this post.");
            }

            var post = await unitOfWork.PostsRead.GetByIdAsync(id, cancellationToken);
            if (post is null)
            {
                return Results.NotFound(ApiResponse<object>.FailureResult("Post not found"));
            }

            if (!IdempotencyEndpointHelper.TryResolveOperationId(httpContext, dto?.OperationId, out var requestOperationId, out var operationError))
            {
                return operationError!;
            }

            var languageValue = dto?.Language ?? "tr";
            var targetRegionValue = dto?.TargetRegion ?? "TR";

            var dispatch = await dispatcher.DispatchAsync(
                new AsyncOperationDispatchRequest<ArticleAnalysisRequestedEvent>(
                    EndpointName: "posts.request-ai-analysis",
                    OperationId: requestOperationId,
                    RequestPayload: new { PostId = id, Language = languageValue, TargetRegion = targetRegionValue },
                    UserId: post.AuthorId,
                    SessionId: null,
                    ResourceId: id.ToString(),
                    BuildEvent: (correlationId, opId, causationId) => new ArticleAnalysisRequestedEvent
                    {
                        OperationId = opId,
                        CorrelationId = correlationId,
                        CausationId = causationId,
                        Payload = new ArticlePayload
                        {
                            ArticleId = post.Id,
                            Title = post.Title,
                            Content = post.Content,
                            AuthorId = post.AuthorId,
                            Visibility = post.Status == PostStatus.Published ? "published" : "restricted",
                            Language = languageValue,
                            TargetRegion = targetRegionValue
                        }
                    },
                    RoutingKey: MessagingConstants.RoutingKeys.AiAnalysisRequested,
                    AcceptedStatusCode: StatusCodes.Status202Accepted,
                    BuildAcceptedResponse: (opId, correlationId) => ApiResponse<RequestAiAnalysisResponseDto>.SuccessResult(
                        new RequestAiAnalysisResponseDto
                        {
                            PostId = id,
                            OperationId = opId,
                            CorrelationId = correlationId,
                            Message = "AI analysis request submitted. Results will be delivered via SignalR."
                        },
                        "AI analysis request accepted")),
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
                        ApiResponse<object>.FailureResult(dispatch.ErrorMessage ?? "AI analysis is temporarily unavailable."),
                        statusCode: StatusCodes.Status503ServiceUnavailable);
                }

                return Results.BadRequest(ApiResponse<object>.FailureResult(dispatch.ErrorMessage ?? "AI analysis request could not be dispatched."));
            }

            return IdempotencyEndpointHelper.BuildStoredResponse(dispatch.Response);
        })
        .WithName("RequestAiAnalysis")
        .WithDescription("Request AI analysis for a post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .Produces<ApiResponse<RequestAiAnalysisResponseDto>>(202)
        .Produces(StatusCodes.Status200OK)
        .Produces(StatusCodes.Status409Conflict)
        .Produces(StatusCodes.Status403Forbidden)
        .Produces(404);

        return app;
    }

    private static ApiResponse<object> BuildPostPartialSuccessResponse(Guid postId, string action)
    {
        return ApiResponse<object>.SuccessResult(
            new
            {
                postId,
                status = "partial_success"
            },
            $"Post {action} successfully, but details could not be fetched. Please fetch manually.");
    }

    private static IResult BuildForbidden(string message)
    {
        return Results.Json(ApiResponse<object>.FailureResult(message), statusCode: StatusCodes.Status403Forbidden);
    }
}

public record UpdateAiAnalysisDto
{
    public string? AiSummary { get; init; }
    public string? AiKeywords { get; init; }
    public int? EstimatedReadingTime { get; init; }
    public string? AiSeoDescription { get; init; }
    public string? AiGeoOptimization { get; init; }
}

public record GenerateAiSummaryResponseDto
{
    public string? Summary { get; init; }
    public int WordCount { get; init; }
    public string OperationId { get; init; } = string.Empty;
    public string? CorrelationId { get; init; }
}

public record RequestAiAnalysisDto
{
    public string? Language { get; init; }
    public string? TargetRegion { get; init; }
    public string? OperationId { get; init; }
}

public record RequestAiAnalysisResponseDto
{
    public Guid PostId { get; init; }
    public string OperationId { get; init; } = string.Empty;
    public string CorrelationId { get; init; } = string.Empty;
    public string Message { get; init; } = string.Empty;
}


