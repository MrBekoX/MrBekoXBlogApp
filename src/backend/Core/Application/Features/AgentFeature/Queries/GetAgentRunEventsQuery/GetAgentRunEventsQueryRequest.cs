using MediatR;
using BlogApp.Core.Application.Common.Models;

namespace BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunEventsQuery;

/// <summary>GET /api/v1/agent/runs/{runId}/events isteği; ``after`` projection
/// olay imleci, ``limit`` sayfa üst sınırı (varsayılan/üst sınır 200).</summary>
public sealed record GetAgentRunEventsQueryRequest : IRequest<Result<AgentRunEventsDto>>
{
    public required Guid RunId { get; init; }

    public long After { get; init; }

    public int? Limit { get; init; }

    public string? GuestSessionId { get; init; }
}

public sealed record AgentRunEventsDto
{
    public required Guid RunId { get; init; }

    public required string RunStatus { get; init; }

    public long LastEventSequence { get; init; }

    public bool HasMore { get; init; }

    public required IReadOnlyList<AgentRunEventDto> Events { get; init; }
}
