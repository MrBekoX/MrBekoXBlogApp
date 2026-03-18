using BlogApp.Server.Domain.Common;
using BlogApp.Server.Domain.Enums;

namespace BlogApp.Server.Domain.Entities;

public class ConsumerInboxMessage : BaseAuditableEntity
{
    public string ConsumerName { get; set; } = string.Empty;
    public string OperationId { get; set; } = string.Empty;
    public Guid? MessageId { get; set; }
    public string? CorrelationId { get; set; }
    public ConsumerInboxStatus Status { get; set; } = ConsumerInboxStatus.Processing;
    public DateTime? ProcessedAt { get; set; }
    public string? LastError { get; set; }
}
