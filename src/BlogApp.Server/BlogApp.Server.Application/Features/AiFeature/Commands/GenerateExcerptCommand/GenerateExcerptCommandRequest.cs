using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateExcerptCommand;

/// <summary>
/// Command request for generating AI excerpt
/// </summary>
public class GenerateExcerptCommandRequest : IRequest<GenerateExcerptCommandResponse>
{
    public string Content { get; set; } = string.Empty;
    public Guid UserId { get; set; }
    
    public string OperationId { get; set; } = string.Empty;
}


