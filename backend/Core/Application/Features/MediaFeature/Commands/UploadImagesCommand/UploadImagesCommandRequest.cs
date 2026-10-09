using BlogApp.Core.Application.Common.Interfaces;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.MediaFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.MediaFeature.Commands.UploadImagesCommand;

public class UploadImagesCommandRequest : IRequest<Result<UploadImagesResultDto>>, IIdempotentCommand
{
    public required List<FileUploadDto> Files { get; init; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "media.upload-images";
    public string? CustomRequestHash { get; set; }
}
