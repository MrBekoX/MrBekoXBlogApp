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
        var group = app.MapGroup("/api/tags")
            .WithTags("Tags");

        // GET /api/tags
        group.MapGet("/", async (
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new GetAllTagQueryRequest(), cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<IEnumerable<GetAllTagQueryDto>>.FailureResult(response.Result.Error!));

            return Results.Ok(ApiResponse<IEnumerable<GetAllTagQueryDto>>.SuccessResult(response.Result.Value!));
        })
        .WithName("GetAllTags")
        .WithDescription("Get all tags")
        .Produces<ApiResponse<IEnumerable<GetAllTagQueryDto>>>(200);

        // POST /api/tags
        group.MapPost("/", async (
            CreateTagCommandDto dto,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new CreateTagCommandRequest
            {
                CreateTagCommandRequestDto = dto
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.BadRequest(ApiResponse<Guid>.FailureResult(response.Result.Error!));

            return Results.Created(
                $"/api/tags/{response.Result.Value}",
                ApiResponse<Guid>.SuccessResult(response.Result.Value!, "Tag created successfully"));
        })
        .WithName("CreateTag")
        .WithDescription("Create a new tag")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor"))
        .Produces<ApiResponse<Guid>>(201)
        .Produces(400);

        // DELETE /api/tags/{id}
        group.MapDelete("/{id:guid}", async (
            Guid id,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new DeleteTagCommandRequest
            {
                Id = id
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.NotFound(ApiResponse<object>.FailureResult(response.Result.Error!));

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
