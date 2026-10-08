using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.TagFeature.Commands.CreateTagCommand;
using BlogApp.Server.Application.Features.TagFeature.Commands.DeleteTagCommand;
using BlogApp.Server.Application.Features.TagFeature.DTOs;
using BlogApp.Server.Application.Features.TagFeature.Queries.GetAllTagQuery;
using BlogApp.Server.Api.Filters;
using BlogApp.Server.Api.Helpers;
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

            return response.ToHttpResult();
        })
        .WithName("GetAllTags")
        .WithDescription("Get all tags. Use includeEmpty=true to include tags without published posts.")
        .CacheOutput("Tags")
        .Produces<ApiResponse<IReadOnlyList<GetAllTagQueryDto>>>(200);

        // POST /api/tags
        group.MapPost("/", async (
            CreateTagCommandDto dto,
            IMediator mediator,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new CreateTagCommandRequest
            {
                CreateTagCommandRequestDto = dto,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            if (!response.IsSuccess)
                return response.ToHttpResult();

            return Results.Created($"/api/tags/{response.Value}",
                ApiResponse<Guid>.SuccessResult(response.Value, "Tag created successfully"));
        })
        .WithName("CreateTag")
        .WithDescription("Create a new tag")
        .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor"))
        .ValidateAntiforgery()
        .Produces<ApiResponse<Guid>>(201)
        .Produces(400);

        // DELETE /api/tags/{id}
        group.MapDelete("/{id:guid}", async (
            Guid id,
            IMediator mediator,
            HttpContext httpContext,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new DeleteTagCommandRequest
            {
                Id = id,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            if (!response.IsSuccess)
                return response.ToHttpResult();

            return Results.NoContent();
        })
        .WithName("DeleteTag")
        .WithDescription("Delete a tag")
        .RequireAuthorization(policy => policy.RequireRole("Admin"))
        .ValidateAntiforgery()
        .Produces(204)
        .Produces(404);

        return app;
    }
}
