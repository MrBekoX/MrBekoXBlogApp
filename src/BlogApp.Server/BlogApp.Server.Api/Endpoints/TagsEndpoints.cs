using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.TagFeature.Commands.CreateTagCommand;
using BlogApp.Server.Application.Features.TagFeature.Commands.DeleteTagCommand;
using BlogApp.Server.Application.Features.TagFeature.DTOs;
using BlogApp.Server.Application.Features.TagFeature.Queries.GetAllTagQuery;
using MediatR;

namespace BlogApp.Server.Api.Endpoints;

public static class TagsEndpoints
{
    public static IEndpointRouteBuilder RegisterTagsEndpoints(this IEndpointRouteBuilder app)
    {
        var versionedGroup = app.NewVersionedApi("Tags");
        var group = versionedGroup.MapGroup("/api/v{version:apiVersion}/tags")
            .HasApiVersion(1.0)
            .WithTags("Tags");

        // GET /api/tags
        group.MapGet("/", async (
            bool? includeEmpty,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new GetAllTagQueryRequest 
            { 
                IncludeEmpty = includeEmpty ?? false 
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<IEnumerable<GetAllTagQueryDto>>.FailureResult(response.Result.Error!));

            return Results.Ok(ApiResponse<IEnumerable<GetAllTagQueryDto>>.SuccessResult(response.Result.Value!));
        })
        .WithName("GetAllTags")
        .WithDescription("Get all tags. Use includeEmpty=true to include tags without published posts.")
        .CacheOutput("Tags")
        .Produces<ApiResponse<IEnumerable<GetAllTagQueryDto>>>(200);

        // POST /api/tags
        group.MapPost("/", async (
            CreateTagCommandDto dto,
            IMediator mediator,
            HttpContext httpContext,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            CancellationToken cancellationToken) =>
        {
            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                httpContext, "CreateTag", dto, unitOfWork, idempotencyService, currentUserService, cancellationToken,
                requireIdempotencyKey: true);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            var response = await mediator.Send(new CreateTagCommandRequest
            {
                CreateTagCommandRequestDto = dto
            }, cancellationToken);

            if (!response.Result.IsSuccess)
            {
                await scope.FailAndCommitAsync(
                    "validation_error", response.Result.Error!, idempotencyService, cancellationToken);
                return Results.BadRequest(ApiResponse<Guid>.FailureResult(response.Result.Error!));
            }

            var result = ApiResponse<Guid>.SuccessResult(response.Result.Value!, "Tag created successfully");
            await scope.CompleteAndCommitAsync(
                StatusCodes.Status201Created, result, idempotencyService, cancellationToken);

            return Results.Created($"/api/tags/{response.Result.Value}", result);
        })
        .WithName("CreateTag")
        .WithDescription("Create a new tag")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor"))
        .Produces<ApiResponse<Guid>>(201)
        .Produces(400)
        .Produces(StatusCodes.Status409Conflict);

        // DELETE /api/tags/{id}
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
                httpContext, "DeleteTag", requestPayload, unitOfWork, idempotencyService, currentUserService, cancellationToken,
                requireIdempotencyKey: true);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            var response = await mediator.Send(new DeleteTagCommandRequest
            {
                Id = id
            }, cancellationToken);

            if (!response.Result.IsSuccess)
            {
                await scope.FailAndCommitAsync(
                    "tag_not_found", response.Result.Error!, idempotencyService, cancellationToken);
                return Results.NotFound(ApiResponse<object>.FailureResult(response.Result.Error!));
            }

            var result = ApiResponse<object>.SuccessResult(new { tagId = id }, "Tag deleted successfully");
            await scope.CompleteAndCommitAsync(
                StatusCodes.Status204NoContent, result, idempotencyService, cancellationToken);

            return Results.NoContent();
        })
        .WithName("DeleteTag")
        .WithDescription("Delete a tag")
        .RequireAuthorization(policy => policy.RequireRole("Admin"))
        .Produces(204)
        .Produces(404);

        return app;
    }
}
