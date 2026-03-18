using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.CollectSourcesCommand;

/// <summary>
/// Command request for collecting web sources
/// </summary>
public class CollectSourcesCommandRequest : IRequest<CollectSourcesCommandResponse>
{
    public string Query { get; set; } = string.Empty;
    public Guid UserId { get; set; }
    
    public string OperationId { get; set; } = string.Empty;
    public int MaxSources { get; set; } = 5;
    public string Language { get; set; } = "tr";
}


