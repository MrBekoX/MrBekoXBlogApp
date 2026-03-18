namespace BlogApp.Server.Domain.Enums;

public enum OutboxMessageStatus
{
    Pending = 0,
    Processing = 1,
    Published = 2,
    Failed = 3
}
