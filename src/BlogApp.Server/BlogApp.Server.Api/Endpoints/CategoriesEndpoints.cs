using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.CategoryFeature.Commands.CreateCategoryCommand;
using BlogApp.Server.Application.Features.CategoryFeature.Commands.DeleteCategoryCommand;
using BlogApp.Server.Application.Features.CategoryFeature.Commands.UpdateCategoryCommand;
using BlogApp.Server.Application.Features.CategoryFeature.DTOs;
using BlogApp.Server.Application.Features.CategoryFeature.Queries.GetAllCategoryQuery;
using BlogApp.Server.Application.Features.CategoryFeature.Queries.GetByIdCategoryQuery;
using MediatR;

namespace BlogApp.Server.Api.Endpoints;

public static class CategoriesEndpoints
{
    public static IEndpointRouteBuilder RegisterCategoriesEndpoints(this IEndpointRouteBuilder app)
    {
        var versionedGroup = app.NewVersionedApi("Categories");
        var group = versionedGroup.MapGroup("/api/v{version:apiVersion}/categories")
            .HasApiVersion(1.0)
            .WithTags("Categories");

        // GET /api/categories
        group.MapGet("/", async (
            bool? includeInactive,
            bool? excludeEmptyCategories,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new GetAllCategoryQueryRequest
            {
                IncludeInactive = includeInactive ?? false,
                ExcludeEmptyCategories = excludeEmptyCategories ?? false
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<IEnumerable<GetAllCategoryQueryDto>>.FailureResult(response.Result.Error!));

            return Results.Ok(ApiResponse<IEnumerable<GetAllCategoryQueryDto>>.SuccessResult(response.Result.Value!));
        })
        .WithName("GetAllCategories")
        .WithDescription("Get all categories")
        .CacheOutput("Categories")
        .Produces<ApiResponse<IEnumerable<GetAllCategoryQueryDto>>>(200);

        // GET /api/categories/{id}
        group.MapGet("/{id:guid}", async (
            Guid id,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new GetByIdCategoryQueryRequest
            {
                Id = id
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<GetByIdCategoryQueryDto>.FailureResult(response.Result.Error!));

            return Results.Ok(ApiResponse<GetByIdCategoryQueryDto>.SuccessResult(response.Result.Value!));
        })
        .WithName("GetCategoryById")
        .WithDescription("Get category by ID")
        .CacheOutput("Categories")
        .Produces<ApiResponse<GetByIdCategoryQueryDto>>(200)
        .Produces(404);

        // POST /api/categories
        group.MapPost("/", async (
            CreateCategoryCommandDto dto,
            IMediator mediator,
            HttpContext httpContext,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            CancellationToken cancellationToken) =>
        {
            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                httpContext, "CreateCategory", dto, unitOfWork, idempotencyService, currentUserService, cancellationToken,
                requireIdempotencyKey: true);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            var response = await mediator.Send(new CreateCategoryCommandRequest
            {
                CreateCategoryCommandRequestDto = dto
            }, cancellationToken);

            if (!response.Result.IsSuccess)
            {
                await scope.FailAndCommitAsync(
                    "validation_error", response.Result.Error!, idempotencyService, cancellationToken);
                return Results.BadRequest(ApiResponse<Guid>.FailureResult(response.Result.Error!));
            }

            var result = ApiResponse<Guid>.SuccessResult(response.Result.Value!, "Category created successfully");
            await scope.CompleteAndCommitAsync(
                StatusCodes.Status201Created, result, idempotencyService, cancellationToken);

            return Results.Created($"/api/categories/{response.Result.Value}", result);
        })
        .WithName("CreateCategory")
        .WithDescription("Create a new category")
        .RequireAuthorization(policy => policy.RequireRole("Admin"))
        .Produces<ApiResponse<Guid>>(201)
        .Produces(400)
        .Produces(StatusCodes.Status409Conflict);

        // PUT /api/categories/{id}
        group.MapPut("/{id:guid}", async (
            Guid id,
            UpdateCategoryCommandDto dto,
            IMediator mediator,
            HttpContext httpContext,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            CancellationToken cancellationToken) =>
        {
            dto.Id = id;

            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                httpContext, "UpdateCategory", dto, unitOfWork, idempotencyService, currentUserService, cancellationToken,
                requireIdempotencyKey: true);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            var response = await mediator.Send(new UpdateCategoryCommandRequest
            {
                UpdateCategoryCommandRequestDto = dto
            }, cancellationToken);

            if (!response.Result.IsSuccess)
            {
                await scope.FailAndCommitAsync(
                    "validation_error", response.Result.Error!, idempotencyService, cancellationToken);
                return Results.BadRequest(ApiResponse<object>.FailureResult(response.Result.Error!));
            }

            await scope.CompleteAndCommitAsync(
                StatusCodes.Status204NoContent,
                new { success = true }, idempotencyService, cancellationToken);

            return Results.NoContent();
        })
        .WithName("UpdateCategory")
        .WithDescription("Update an existing category")
        .RequireAuthorization(policy => policy.RequireRole("Admin"))
        .Produces(204)
        .Produces(400)
        .Produces(404)
        .Produces(StatusCodes.Status409Conflict);

        // DELETE /api/categories/{id}
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
                httpContext, "DeleteCategory", requestPayload, unitOfWork, idempotencyService, currentUserService, cancellationToken,
                requireIdempotencyKey: true);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            var response = await mediator.Send(new DeleteCategoryCommandRequest
            {
                Id = id
            }, cancellationToken);

            if (!response.Result.IsSuccess)
            {
                await scope.FailAndCommitAsync(
                    "category_not_found", response.Result.Error!, idempotencyService, cancellationToken);
                return Results.NotFound(ApiResponse<object>.FailureResult(response.Result.Error!));
            }

            var result = ApiResponse<object>.SuccessResult(new { categoryId = id }, "Category deleted successfully");
            await scope.CompleteAndCommitAsync(
                StatusCodes.Status204NoContent, result, idempotencyService, cancellationToken);

            return Results.NoContent();
        })
        .WithName("DeleteCategory")
        .WithDescription("Delete a category")
        .RequireAuthorization(policy => policy.RequireRole("Admin"))
        .Produces(204)
        .Produces(404);

        return app;
    }
}
