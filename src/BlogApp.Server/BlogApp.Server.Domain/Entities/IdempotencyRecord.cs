using BlogApp.Server.Domain.Common;
using BlogApp.Server.Domain.Enums;

namespace BlogApp.Server.Domain.Entities;

public class IdempotencyRecord : BaseAuditableEntity
{
    public string EndpointName { get; set; } = string.Empty;
    public string OperationId { get; set; } = string.Empty;
    public string RequestHash { get; set; } = string.Empty;
    public string CorrelationId { get; set; } = string.Empty;
    public string? CausationId { get; set; }
    public IdempotencyRecordStatus Status { get; set; } = IdempotencyRecordStatus.Processing;
    public int? AcceptedHttpStatus { get; set; }
    public string? AcceptedResponseJson { get; set; }
    public int? FinalHttpStatus { get; set; }
    public string? FinalResponseJson { get; set; }
    public string? FinalResponseHeadersJson { get; set; }
    public Guid? UserId { get; set; }
    public string? SessionId { get; set; }
    public string? ResourceId { get; set; }
    public string? ErrorCode { get; set; }
    public string? ErrorMessage { get; set; }
    public DateTime? CompletedAt { get; set; }
}
