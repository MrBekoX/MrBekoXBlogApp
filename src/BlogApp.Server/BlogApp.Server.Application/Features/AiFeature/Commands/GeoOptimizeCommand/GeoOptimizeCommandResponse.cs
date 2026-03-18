using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GeoOptimizeCommand;

/// <summary>
/// Response for GEO optimization
/// </summary>
public class GeoOptimizeCommandResponse : IAiOperationResponse
{
    public string OperationId { get; set; } = string.Empty;
    public string? CorrelationId { get; set; }
    public bool IsProcessing { get; set; }
    public string? ErrorCode { get; set; }
    public string? ErrorMessage { get; set; }
    public Result<GeoOptimizationResult> Data { get; set; } = null!;
}

/// <summary>
/// GEO optimization result
/// </summary>
public class GeoOptimizationResult : IAiOperationResponse
{
    public string OperationId { get; set; } = string.Empty;
    public string? CorrelationId { get; set; }
    public bool IsProcessing { get; set; }
    public string? ErrorCode { get; set; }
    public string? ErrorMessage { get; set; }
    public string TargetRegion { get; set; } = string.Empty;
    public string LocalizedTitle { get; set; } = string.Empty;
    public string LocalizedSummary { get; set; } = string.Empty;
    public string[] LocalizedKeywords { get; set; } = [];
    public string CulturalNotes { get; set; } = string.Empty;
}


