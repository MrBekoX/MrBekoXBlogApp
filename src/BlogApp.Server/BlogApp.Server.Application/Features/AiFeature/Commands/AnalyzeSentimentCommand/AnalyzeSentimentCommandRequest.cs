using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.AnalyzeSentimentCommand;

/// <summary>
/// Command request for AI sentiment analysis
/// </summary>
public class AnalyzeSentimentCommandRequest : IRequest<AnalyzeSentimentCommandResponse>
{
    public string Content { get; set; } = string.Empty;
    public Guid UserId { get; set; }
    
    public string OperationId { get; set; } = string.Empty;
    public string Language { get; set; } = "tr";
}


