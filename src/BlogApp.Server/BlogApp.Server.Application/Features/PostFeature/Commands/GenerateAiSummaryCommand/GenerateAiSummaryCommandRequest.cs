using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.GenerateAiSummaryCommand;

/// <summary>
/// Command request for generating AI summary for a post.
/// </summary>
public class GenerateAiSummaryCommandRequest : IRequest<GenerateAiSummaryCommandResponse>
{
    public Guid PostId { get; set; }
    public int MaxSentences { get; set; } = 3;
    public string Language { get; set; } = "tr";
    public string OperationId { get; set; } = string.Empty;
}
