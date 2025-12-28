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
        var group = app.MapGroup("/api/categories")
            .WithTags("Categories");

        // GET /api/categories
        group.MapGet("/", async (
            bool? includeInactive,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new GetAllCategoryQueryRequest
            {
                IncludeInactive = includeInactive ?? false
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
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new CreateCategoryCommandRequest
            {
                CreateCategoryCommandRequestDto = dto
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.BadRequest(ApiResponse<Guid>.FailureResult(response.Result.Error!));

            return Results.Created(
                $"/api/categories/{response.Result.Value}",
                ApiResponse<Guid>.SuccessResult(response.Result.Value!, "Category created successfully"));
        })
        .WithName("CreateCategory")
        .WithDescription("Create a new category")
        .RequireAuthorization(policy => policy.RequireRole("Admin"))
        .Produces<ApiResponse<Guid>>(201)
        .Produces(400);

        // PUT /api/categories/{id}
        group.MapPut("/{id:guid}", async (
            Guid id,
            UpdateCategoryCommandDto dto,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            dto.Id = id;

            var response = await mediator.Send(new UpdateCategoryCommandRequest
            {
                UpdateCategoryCommandRequestDto = dto
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.BadRequest(ApiResponse<object>.FailureResult(response.Result.Error!));

            return Results.NoContent();
        })
        .WithName("UpdateCategory")
        .WithDescription("Update an existing category")
        .RequireAuthorization(policy => policy.RequireRole("Admin"))
        .Produces(204)
        .Produces(400)
        .Produces(404);

        // DELETE /api/categories/{id}
        group.MapDelete("/{id:guid}", async (
            Guid id,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new DeleteCategoryCommandRequest
            {
                Id = id
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<object>.FailureResult(response.Result.Error!));

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
