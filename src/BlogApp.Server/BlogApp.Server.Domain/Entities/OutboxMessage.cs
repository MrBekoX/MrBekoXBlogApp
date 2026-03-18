using BlogApp.Server.Domain.Common;
using BlogApp.Server.Domain.Enums;

namespace BlogApp.Server.Domain.Entities;

public class OutboxMessage : BaseAuditableEntity
{
    public Guid MessageId { get; set; }
    public string OperationId { get; set; } = string.Empty;
    public string? CorrelationId { get; set; }
    public string? CausationId { get; set; }
    public string RoutingKey { get; set; } = string.Empty;
    public string EventType { get; set; } = string.Empty;
    public string PayloadJson { get; set; } = string.Empty;
    public string? HeadersJson { get; set; }
    public OutboxMessageStatus Status { get; set; } = OutboxMessageStatus.Pending;
    public int AttemptCount { get; set; }
    public DateTime NextAttemptAt { get; set; } = DateTime.UtcNow;
    public string? LastError { get; set; }
    public DateTime? PublishedAt { get; set; }
}
