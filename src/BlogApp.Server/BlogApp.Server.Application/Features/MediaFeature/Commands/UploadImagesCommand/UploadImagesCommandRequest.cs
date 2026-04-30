using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Features.MediaFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.MediaFeature.Commands.UploadImagesCommand;

public class UploadImagesCommandRequest : IRequest<UploadImagesCommandResponse>, IIdempotentCommand
{
    public required List<FileUploadDto> Files { get; init; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "media.upload-images";
    public string? CustomRequestHash { get; set; }
}
