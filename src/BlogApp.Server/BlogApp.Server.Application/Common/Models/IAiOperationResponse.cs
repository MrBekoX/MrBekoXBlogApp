namespace BlogApp.Server.Application.Common.Models;

public interface IAiOperationResponse
{
    string OperationId { get; set; }
    string? CorrelationId { get; set; }
    bool IsProcessing { get; set; }
    string? ErrorCode { get; set; }
    string? ErrorMessage { get; set; }
}
