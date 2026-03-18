using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GenerateSeoDescriptionCommand;

/// <summary>
/// Command request for generating AI SEO description
/// </summary>
public class GenerateSeoDescriptionCommandRequest : IRequest<GenerateSeoDescriptionCommandResponse>
{
    public string Content { get; set; } = string.Empty;
    public Guid UserId { get; set; }
    
    public string OperationId { get; set; } = string.Empty;
}


