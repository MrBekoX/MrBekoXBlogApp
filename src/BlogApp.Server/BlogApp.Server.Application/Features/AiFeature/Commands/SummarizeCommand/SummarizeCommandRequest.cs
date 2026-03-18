using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.SummarizeCommand;

/// <summary>
/// Command request for AI summarization
/// </summary>
public class SummarizeCommandRequest : IRequest<SummarizeCommandResponse>
{
    public string Content { get; set; } = string.Empty;
    public Guid UserId { get; set; }
    
    public string OperationId { get; set; } = string.Empty;
    public int MaxSentences { get; set; } = 5;
    public string Language { get; set; } = "tr";
}


