using MediatR;

namespace BlogApp.Server.Application.Features.AiFeature.Commands.GeoOptimizeCommand;

/// <summary>
/// Command request for GEO optimization
/// </summary>
public class GeoOptimizeCommandRequest : IRequest<GeoOptimizeCommandResponse>
{
    public string Content { get; set; } = string.Empty;
    public Guid UserId { get; set; }
    
    public string OperationId { get; set; } = string.Empty;
    public string TargetRegion { get; set; } = "TR";
    public string Language { get; set; } = "tr";
}


