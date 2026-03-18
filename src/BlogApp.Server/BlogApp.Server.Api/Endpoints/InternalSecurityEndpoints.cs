using BlogApp.Server.Api.Filters;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Common.Security;

namespace BlogApp.Server.Api.Endpoints;

public static class InternalSecurityEndpoints
{
    public static IEndpointRouteBuilder RegisterInternalSecurityEndpoints(this IEndpointRouteBuilder app)
    {
        var versionedGroup = app.NewVersionedApi("InternalSecurity");
        var group = versionedGroup.MapGroup("/internal/v{version:apiVersion}/ai")
            .HasApiVersion(1.0)
            .WithTags("Internal");

        group.AddEndpointFilter<InternalServiceAuthorizationFilter>();

        group.MapPost("/post-access", async (
            InternalPostAuthorizationRequest request,
            IPostAuthorizationService postAuthorizationService,
            CancellationToken cancellationToken) =>
        {
            var subject = request.ToSubject();
            var decision = await postAuthorizationService.AuthorizeAsync(
                request.PostId,
                subject,
                request.Action,
                cancellationToken);

            var response = new InternalPostAuthorizationResponse
            {
                Allowed = decision.IsAuthorized,
                PostId = request.PostId,
                AuthorId = decision.AuthorId,
                Visibility = !decision.Exists
                    ? "not_found"
                    : decision.Status == BlogApp.Server.Domain.Enums.PostStatus.Published
                        ? "published"
                        : "restricted"
            };

            return Results.Ok(ApiResponse<InternalPostAuthorizationResponse>.SuccessResult(response));
        })
        .WithName("AuthorizePostAccess")
        .WithDescription("Internal authorization decision endpoint for AI service")
        .ExcludeFromDescription();

        return app;
    }
}

public sealed record InternalPostAuthorizationRequest
{
    public string SubjectType { get; init; } = "anonymous";
    public string? SubjectId { get; init; }
    public List<string> Roles { get; init; } = [];
    public Guid PostId { get; init; }
    public PostAuthorizationAction Action { get; init; }

    public PostAuthorizationSubject ToSubject()
    {
        var isAuthenticated = !string.Equals(SubjectType, "anonymous", StringComparison.OrdinalIgnoreCase);
        var parsedUserId = Guid.TryParse(SubjectId, out var userId)
            ? userId
            : (Guid?)null;

        return new PostAuthorizationSubject(parsedUserId, isAuthenticated, Roles);
    }
}

public sealed record InternalPostAuthorizationResponse
{
    public bool Allowed { get; init; }
    public Guid PostId { get; init; }
    public Guid? AuthorId { get; init; }
    public string Visibility { get; init; } = "not_found";
}
