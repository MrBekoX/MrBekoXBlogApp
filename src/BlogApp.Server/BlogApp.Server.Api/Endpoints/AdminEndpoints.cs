using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Features.AdminFeature.DTOs;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace BlogApp.Server.Api.Endpoints;

public static class AdminEndpoints
{
    public static IEndpointRouteBuilder RegisterAdminEndpoints(this IEndpointRouteBuilder app)
    {
        var group = app.MapGroup("/api/admin")
            .WithTags("Admin")
            .RequireAuthorization(policy => policy.RequireRole("Admin"));

        // Quarantine stats endpoint
        group.MapGet("/quarantine/stats", async (
            IAdminService adminService,
            CancellationToken cancellationToken) =>
        {
            var stats = await adminService.GetQuarantineStatsAsync(cancellationToken);
            return Results.Ok(stats);
        })
        .WithName("GetQuarantineStats")
        .Produces<QuarantineStatsResponseDto>(StatusCodes.Status200OK);

        // Queue stats endpoint
        group.MapGet("/queue/stats", async (
            IAdminService adminService,
            CancellationToken cancellationToken) =>
        {
            var stats = await adminService.GetQueueStatsAsync(cancellationToken);
            return Results.Ok(stats);
        })
        .WithName("GetQueueStats")
        .Produces<QueueStatsResponseDto>(StatusCodes.Status200OK);

        // Quarantine replay endpoint
        group.MapPost("/quarantine/replay", async (
            [FromBody] ReplayQuarantineCommandDto request,
            HttpContext httpContext,
            IAdminService adminService,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            CancellationToken cancellationToken) =>
        {
            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                httpContext,
                "AdminReplayQuarantine",
                request,
                unitOfWork,
                idempotencyService,
                currentUserService,
                cancellationToken,
                requireIdempotencyKey: true);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            try
            {
                var result = await adminService.ReplayQuarantineMessagesAsync(
                    request.MaxMessages,
                    request.DryRun,
                    request.TaxonomyPrefixes,
                    request.MaxAgeSeconds,
                    cancellationToken);

                await scope.CompleteAndCommitAsync(
                    StatusCodes.Status200OK,
                    result,
                    idempotencyService,
                    cancellationToken,
                    httpContext.Response);

                return Results.Ok(result);
            }
            catch
            {
                throw;
            }
        })
        .WithName("ReplayQuarantine")
        .Produces<QuarantineReplayResponseDto>(StatusCodes.Status200OK);

        return app;
    }
}
