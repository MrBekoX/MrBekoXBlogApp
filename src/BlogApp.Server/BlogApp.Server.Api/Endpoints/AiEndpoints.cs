using System.Security.Claims;
using BlogApp.BuildingBlocks.Messaging;
using BlogApp.BuildingBlocks.Messaging.Abstractions;
using BlogApp.Server.Application.Features.AiFeature.Commands.GenerateTitleCommand;
using BlogApp.Server.Application.Features.AiFeature.Commands.GenerateExcerptCommand;
using BlogApp.Server.Application.Features.AiFeature.Commands.GenerateTagsCommand;
using BlogApp.Server.Application.Features.AiFeature.Commands.GenerateSeoDescriptionCommand;
using BlogApp.Server.Application.Features.AiFeature.Commands.ImproveContentCommand;
using MediatR;
using Microsoft.AspNetCore.Authorization;
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

        // POST /api/ai/generate-title
        group.MapPost("/generate-title", async (
            GenerateTitleRequest request,
            IMediator mediator,
            ClaimsPrincipal user,
            CancellationToken cancellationToken) =>
        {
            var userIdClaim = user.FindFirst(NameIdentifier)?.Value;
            if (string.IsNullOrEmpty(userIdClaim) || !Guid.TryParse(userIdClaim, out var userId))
                return Results.Unauthorized();
                
            var response = await mediator.Send(new GenerateTitleCommandRequest
            {
                Content = request.Content,
                UserId = userId
            }, cancellationToken);

            return Results.Ok(response.Data);
        })
        .WithName("GenerateTitle")
        .Produces<string>(StatusCodes.Status200OK)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized)
        .ProducesProblem(StatusCodes.Status500InternalServerError);

        // POST /api/ai/generate-excerpt
        group.MapPost("/generate-excerpt", async (
            GenerateExcerptRequest request,
            IMediator mediator,
            ClaimsPrincipal user,
            CancellationToken cancellationToken) =>
        {
            var userIdClaim = user.FindFirst(NameIdentifier)?.Value;
            if (string.IsNullOrEmpty(userIdClaim) || !Guid.TryParse(userIdClaim, out var userId))
                return Results.Unauthorized();
                
            var response = await mediator.Send(new GenerateExcerptCommandRequest
            {
                Content = request.Content,
                UserId = userId
            }, cancellationToken);

            return Results.Ok(response.Data);
        })
        .WithName("GenerateExcerpt")
        .Produces<string>(StatusCodes.Status200OK)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized)
        .ProducesProblem(StatusCodes.Status500InternalServerError);

        // POST /api/ai/generate-tags
        group.MapPost("/generate-tags", async (
            GenerateTagsRequest request,
            IMediator mediator,
            ClaimsPrincipal user,
            CancellationToken cancellationToken) =>
        {
            var userIdClaim = user.FindFirst(NameIdentifier)?.Value;
            if (string.IsNullOrEmpty(userIdClaim) || !Guid.TryParse(userIdClaim, out var userId))
                return Results.Unauthorized();
                
            var response = await mediator.Send(new GenerateTagsCommandRequest
            {
                Content = request.Content,
                UserId = userId
            }, cancellationToken);

            return Results.Ok(response.Data);
        })
        .WithName("GenerateTags")
        .Produces<string[]>(StatusCodes.Status200OK)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized)
        .ProducesProblem(StatusCodes.Status500InternalServerError);

        // POST /api/ai/generate-seo
        group.MapPost("/generate-seo", async (
            GenerateSeoRequest request,
            IMediator mediator,
            ClaimsPrincipal user,
            CancellationToken cancellationToken) =>
        {
            var userIdClaim = user.FindFirst(NameIdentifier)?.Value;
            if (string.IsNullOrEmpty(userIdClaim) || !Guid.TryParse(userIdClaim, out var userId))
                return Results.Unauthorized();
                
            var response = await mediator.Send(new GenerateSeoDescriptionCommandRequest
            {
                Content = request.Content,
                UserId = userId
            }, cancellationToken);

            return Results.Ok(response.Data);
        })
        .WithName("GenerateSeoDescription")
        .Produces<string>(StatusCodes.Status200OK)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized)
        .ProducesProblem(StatusCodes.Status500InternalServerError);

        // POST /api/ai/improve-content
        group.MapPost("/improve-content", async (
            ImproveContentRequest request,
            IMediator mediator,
            ClaimsPrincipal user,
            CancellationToken cancellationToken) =>
        {
            var userIdClaim = user.FindFirst(NameIdentifier)?.Value;
            if (string.IsNullOrEmpty(userIdClaim) || !Guid.TryParse(userIdClaim, out var userId))
                return Results.Unauthorized();
                
            var response = await mediator.Send(new ImproveContentCommandRequest
            {
                Content = request.Content,
                UserId = userId
            }, cancellationToken);

            return Results.Ok(response.Data);
        })
        .WithName("ImproveContent")
        .Produces<string>(StatusCodes.Status200OK)
        .ProducesProblem(StatusCodes.Status400BadRequest)
        .ProducesProblem(StatusCodes.Status401Unauthorized)
        .ProducesProblem(StatusCodes.Status500InternalServerError);

        return app;
    }
}

// Request DTOs
public record GenerateTitleRequest(string Content);
public record GenerateExcerptRequest(string Content);
public record GenerateTagsRequest(string Content);
public record GenerateSeoRequest(string Content);
public record ImproveContentRequest(string Content);

// Response DTOs
public record GenerateTitleResponse(string Title);
public record GenerateExcerptResponse(string Excerpt);
public record GenerateTagsResponse(string[] Tags);
public record GenerateSeoResponse(string Description);
public record ImproveContentResponse(string Content);
