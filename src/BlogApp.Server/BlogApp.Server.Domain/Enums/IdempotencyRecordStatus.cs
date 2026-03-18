namespace BlogApp.Server.Domain.Enums;

public enum IdempotencyRecordStatus
{
    Processing = 0,
    Completed = 1,
    Failed = 2
}
