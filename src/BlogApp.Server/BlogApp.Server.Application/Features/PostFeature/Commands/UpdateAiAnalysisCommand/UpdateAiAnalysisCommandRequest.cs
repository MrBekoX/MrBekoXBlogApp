using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.UpdateAiAnalysisCommand;

/// <summary>
/// Command request for updating AI analysis results of a post
/// </summary>
public class UpdateAiAnalysisCommandRequest : IRequest<UpdateAiAnalysisCommandResponse>
{
    public Guid PostId { get; set; }
    public string? AiSummary { get; set; }
    public string? AiKeywords { get; set; }
    public int? AiEstimatedReadingTime { get; set; }
    public string? AiSeoDescription { get; set; }
    public string? AiGeoOptimization { get; set; }
}
