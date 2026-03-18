using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.ExtractKeywordsCommand;

/// <summary>
/// Command request for AI keywords extraction
/// </summary>
public class ExtractKeywordsCommandRequest : IRequest<ExtractKeywordsCommandResponse>
{
    public string Content { get; set; } = string.Empty;
    public Guid UserId { get; set; }
    
    public string OperationId { get; set; } = string.Empty;
    public int MaxKeywords { get; set; } = 10;
    public string Language { get; set; } = "tr";
}


