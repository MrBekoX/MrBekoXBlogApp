using System.Security.Claims;
using BlogApp.Server.Api.Extensions;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.PostFeature.Commands.CreatePostCommand;
using BlogApp.Server.Application.Features.PostFeature.Commands.DeletePostCommand;
using BlogApp.Server.Application.Features.PostFeature.Commands.PublishPostCommand;
using BlogApp.Server.Application.Features.PostFeature.Commands.SaveDraftCommand;
using BlogApp.Server.Application.Features.PostFeature.Commands.UpdatePostCommand;
using BlogApp.Server.Application.Features.PostFeature.DTOs;
using BlogApp.Server.Application.Features.PostFeature.Queries.GetMyPostsQuery;
using BlogApp.Server.Application.Features.PostFeature.Queries.GetPostByIdQuery;
using BlogApp.Server.Application.Features.PostFeature.Queries.GetPostBySlugQuery;
using BlogApp.Server.Application.Features.PostFeature.Queries.GetPostsListQuery;
using BlogApp.Server.Application.Common.Security;
using BlogApp.Server.Domain.Enums;
using BlogApp.Server.Api.Filters;
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
                PageSize = Math.Min(pageSize is null or 0 ? 10 : pageSize.Value, 100),
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
        .Produces<ApiResponse<PaginatedList<PostListQueryDto>>>(200);

        group.MapGet("/featured", async (
            int? pageSize,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new GetPostsListQueryRequest
            {
                PageSize = Math.Min(pageSize is null or 0 ? 5 : pageSize.Value, 100),
                IsFeatured = true,
                Status = PostStatus.Published,
                SortDescending = true
            }, cancellationToken);

            return Results.Ok(ApiResponse<PaginatedList<PostListQueryDto>>.SuccessResult(response.Result));
        })
        .WithName("GetFeaturedPosts")
        .WithDescription("Get featured posts")
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
                effectiveAuthorId = subject.UserId;

            var response = await mediator.Send(new GetPostsListQueryRequest
            {
                PageNumber = page is null or 0 ? 1 : page.Value,
                PageSize = Math.Min(pageSize is null or 0 ? 10 : pageSize.Value, 100),
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
                PageSize = Math.Min(pageSize is null or 0 ? 10 : pageSize.Value, 100)
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
                return Results.NotFound(ApiResponse<PostDetailQueryDto>.FailureResult("Post not found"));

            var response = await mediator.Send(new GetPostByIdQueryRequest
            {
                Id = id,
                RequirePublishedStatus = decision.Status == PostStatus.Published
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<PostDetailQueryDto>.FailureResult(response.Result.Error!));

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
        .Produces<ApiResponse<PostDetailQueryDto>>(200)
        .Produces(404);

        group.MapPost("/", async (
            CreatePostCommandDto dto,
            IMediator mediator,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new CreatePostCommandRequest
            {
                CreatePostCommandRequestDto = dto,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.BadRequest(ApiResponse<Guid>.FailureResult(response.Result.Error!));

            return Results.Created($"/api/posts/{response.Result.Value}",
                ApiResponse<Guid>.SuccessResult(response.Result.Value, "Post created successfully"));
        })
        .WithName("CreatePost")
        .WithDescription("Create a new post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .ValidateAntiforgery()
        .Produces<ApiResponse<Guid>>(201)
        .Produces(400)
        .Produces(401);

        group.MapPut("/{id:guid}", async (
            Guid id,
            UpdatePostCommandDto dto,
            IMediator mediator,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            dto.Id = id;

            var response = await mediator.Send(new UpdatePostCommandRequest
            {
                UpdatePostCommandRequestDto = dto,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.BadRequest(ApiResponse<object>.FailureResult(response.Result.Error!));

            return Results.Ok(ApiResponse<object>.SuccessResult(new { postId = id }, "Post updated successfully"));
        })
        .WithName("UpdatePost")
        .WithDescription("Update an existing post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .ValidateAntiforgery()
        .Produces<ApiResponse<object>>(200)
        .Produces(400)
        .Produces(404);

        group.MapDelete("/{id:guid}", async (
            Guid id,
            IMediator mediator,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new DeletePostCommandRequest
            {
                Id = id,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<object>.FailureResult(response.Result.Error!));

            return Results.NoContent();
        })
        .WithName("DeletePost")
        .WithDescription("Delete a post (soft delete)")
        .RequireAuthorization(policy => policy.RequireRole("Admin"))
        .ValidateAntiforgery()
        .Produces(204)
        .Produces(404);

        group.MapPost("/{id:guid}/publish", async (
            Guid id,
            IMediator mediator,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new PublishPostCommandRequest
            {
                Id = id,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            if (response.IsProcessing)
            {
                return Results.Accepted(value: ApiResponse<object>.SuccessResult(
                    new { response.OperationId, response.CorrelationId, status = "Processing" },
                    response.ErrorMessage ?? "Publish request is still processing."));
            }

            if (string.Equals(response.ErrorCode, "operation_conflict", StringComparison.Ordinal))
            {
                return Results.Conflict(ApiResponse<object>.FailureResult(
                    response.ErrorMessage ?? "The same operationId was used with a different payload."));
            }

            if (!response.Result.IsSuccess)
            {
                if (string.Equals(response.ErrorCode, "post_not_found", StringComparison.Ordinal))
                    return Results.NotFound(ApiResponse<object>.FailureResult(response.Result.Error!));

                return Results.BadRequest(ApiResponse<object>.FailureResult(response.Result.Error!));
            }

            return Results.Ok(ApiResponse<object>.SuccessResult(
                new { postId = id }, "Post published successfully"));
        })
        .WithName("PublishPost")
        .WithDescription("Publish a post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor"))
        .ValidateAntiforgery()
        .Produces<ApiResponse<object>>(200)
        .Produces(StatusCodes.Status202Accepted)
        .Produces(StatusCodes.Status409Conflict)
        .Produces(404);

        group.MapPost("/{id:guid}/unpublish", async (
            Guid id,
            IMediator mediator,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new UnpublishPostCommandRequest
            {
                Id = id,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<object>.FailureResult(response.Result.Error!));

            return Results.Ok(ApiResponse<object>.SuccessResult(
                new { postId = id }, "Post unpublished successfully"));
        })
        .WithName("UnpublishPost")
        .WithDescription("Unpublish a post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor"))
        .ValidateAntiforgery()
        .Produces<ApiResponse<object>>(200)
        .Produces(404);

        group.MapPost("/{id:guid}/archive", async (
            Guid id,
            IMediator mediator,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new UnpublishPostCommandRequest
            {
                Id = id,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<object>.FailureResult(response.Result.Error!));

            return Results.Ok(ApiResponse<object>.SuccessResult(
                new { postId = id }, "Post archived successfully"));
        })
        .WithName("ArchivePost")
        .WithDescription("Archive a post")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor"))
        .ValidateAntiforgery()
        .Produces<ApiResponse<object>>(200)
        .Produces(404);

        group.MapPost("/draft", async (
            SaveDraftCommandDto dto,
            IMediator mediator,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new SaveDraftCommandRequest
            {
                SaveDraftCommandRequestDto = dto,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.BadRequest(ApiResponse<Guid>.FailureResult(response.Result.Error!));

            return Results.Ok(ApiResponse<Guid>.SuccessResult(response.Result.Value, "Draft saved"));
        })
        .WithName("SaveDraft")
        .WithDescription("Save draft (auto-save endpoint)")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .ValidateAntiforgery()
        .Produces<ApiResponse<Guid>>(200)
        .Produces(400);

        group.MapPut("/draft", async (
            SaveDraftCommandDto dto,
            IMediator mediator,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new SaveDraftCommandRequest
            {
                SaveDraftCommandRequestDto = dto,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.BadRequest(ApiResponse<Guid>.FailureResult(response.Result.Error!));

            return Results.Ok(ApiResponse<Guid>.SuccessResult(response.Result.Value, "Draft saved"));
        })
        .WithName("UpdateDraft")
        .WithDescription("Update draft (auto-save endpoint)")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"))
        .ValidateAntiforgery()
        .Produces<ApiResponse<Guid>>(200)
        .Produces(400);

        return app;
    }
}
