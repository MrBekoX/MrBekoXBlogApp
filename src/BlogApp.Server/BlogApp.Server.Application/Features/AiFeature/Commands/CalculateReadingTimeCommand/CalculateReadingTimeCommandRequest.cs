using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.CalculateReadingTimeCommand;

/// <summary>
/// Command request for calculating reading time
/// </summary>
public class CalculateReadingTimeCommandRequest : IRequest<CalculateReadingTimeCommandResponse>
{
    public string Content { get; set; } = string.Empty;
    public Guid UserId { get; set; }
    
    public string OperationId { get; set; } = string.Empty;
}


