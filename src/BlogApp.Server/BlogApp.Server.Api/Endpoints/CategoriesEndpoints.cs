using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.CategoryFeature.Commands.CreateCategoryCommand;
using BlogApp.Server.Application.Features.CategoryFeature.Commands.DeleteCategoryCommand;
using BlogApp.Server.Application.Features.CategoryFeature.Commands.UpdateCategoryCommand;
using BlogApp.Server.Application.Features.CategoryFeature.DTOs;
using BlogApp.Server.Application.Features.CategoryFeature.Queries.GetAllCategoryQuery;
using BlogApp.Server.Application.Features.CategoryFeature.Queries.GetByIdCategoryQuery;
using BlogApp.Server.Api.Filters;
using BlogApp.Server.Api.Helpers;
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

            if (!response.IsSuccess)
                return response.ToHttpResult();

            return Results.Ok(ApiResponse<IReadOnlyList<GetAllCategoryQueryDto>>.SuccessResult(response.Value!));
        })
        .WithName("GetAllCategories")
        .WithDescription("Get all categories")
        .CacheOutput("Categories")
        .Produces<ApiResponse<IReadOnlyList<GetAllCategoryQueryDto>>>(200);

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

            if (!response.IsSuccess)
                return response.ToHttpResult();

            return Results.Ok(ApiResponse<GetByIdCategoryQueryDto>.SuccessResult(response.Value!));
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
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new CreateCategoryCommandRequest
            {
                CreateCategoryCommandRequestDto = dto,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            if (!response.IsSuccess)
                return response.ToHttpResult();

            return Results.Created($"/api/categories/{response.Value}",
                ApiResponse<Guid>.SuccessResult(response.Value, "Category created successfully"));
        })
        .WithName("CreateCategory")
        .WithDescription("Create a new category")
        .RequireAuthorization(policy => policy.RequireRole("Admin"))
        .ValidateAntiforgery()
        .Produces<ApiResponse<Guid>>(201)
        .Produces(400);

        // PUT /api/categories/{id}
        group.MapPut("/{id:guid}", async (
            Guid id,
            UpdateCategoryCommandDto dto,
            IMediator mediator,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            dto.Id = id;

            var response = await mediator.Send(new UpdateCategoryCommandRequest
            {
                UpdateCategoryCommandRequestDto = dto,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            if (!response.IsSuccess)
                return response.ToHttpResult();

            return Results.NoContent();
        })
        .WithName("UpdateCategory")
        .WithDescription("Update an existing category")
        .RequireAuthorization(policy => policy.RequireRole("Admin"))
        .ValidateAntiforgery()
        .Produces(204)
        .Produces(400)
        .Produces(404);

        // DELETE /api/categories/{id}
        group.MapDelete("/{id:guid}", async (
            Guid id,
            IMediator mediator,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new DeleteCategoryCommandRequest
            {
                Id = id,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            if (!response.IsSuccess)
                return response.ToHttpResult();

            return Results.NoContent();
        })
        .WithName("DeleteCategory")
        .WithDescription("Delete a category")
        .RequireAuthorization(policy => policy.RequireRole("Admin"))
        .ValidateAntiforgery()
        .Produces(204)
        .Produces(404);

        return app;
    }
}
