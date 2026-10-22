using MediatR;
using BlogApp.Core.Application.Common.Models;

namespace BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunQuery;

/// <summary>GET /api/v1/agent/runs/{runId} isteği; GuestSessionId sunucu tarafı
/// misafir oturum çerezinden Presentation tarafından verilir (K5).</summary>
public sealed record GetAgentRunQueryRequest : IRequest<Result<AgentRunStatusDto>>
{
    public required Guid RunId { get; init; }

    public string? GuestSessionId { get; init; }
}

/// <summary>Run durum/projection görüntüsü (B10 replay+durum sözleşmesi).
/// Kabul (Accepted), başlama (SelectedMode dolması / olay akışı) ve terminal
/// durumlar AYRI alanlarla taşınır; terminalde izin verilen sonuç eklenir.</summary>
public sealed record AgentRunStatusDto
{
    public required Guid RunId { get; init; }

    public Guid ConversationId { get; init; }

    public long TurnSequence { get; init; }

    /// <summary>Accepted | Completed | PartiallyCompleted | Failed | Cancelled.</summary>
    public required string Status { get; init; }

    public string ModePreference { get; init; } = string.Empty;

    public string? SelectedMode { get; init; }

    public string? SourceScope { get; init; }

    public string Question { get; init; } = string.Empty;

    public string Language { get; init; } = string.Empty;

    public Guid? ArticleId { get; init; }

    /// <summary>Kabulde normalize edilen konu: <c>auto</c> | <c>who_am_i</c> (eski kayıtlar auto).
    /// İstemci reload/reconnect sonrası konuyu buradan doğrular (K7).</summary>
    public string ConversationTopic { get; init; } = "auto";

    /// <summary>Run'ın kabulde kararlaşan wire sürümü (1 | 2); run boyunca değişmez (K4).</summary>
    public int WireVersion { get; init; } = 1;

    public DateTimeOffset AcceptedAt { get; init; }

    public DateTimeOffset DeadlineAt { get; init; }

    public DateTimeOffset? TerminalAt { get; init; }

    /// <summary>Projection'ın uyguladığı en büyük olay sırası; istemci replay
    /// imleci (``after``) bununla ilerletilir.</summary>
    public long LastEventSequence { get; init; }

    /// <summary>Terminalde izin verilen sonuç; terminal değilken veya sunum
    /// denetimi engellediğinde içerik alanları boş olabilir.</summary>
    public AgentRunResultDto? Result { get; init; }
}
