using BlogApp.Core.Application.Common.Interfaces;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.MediaFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.MediaFeature.Commands.UploadImageCommand;

public class UploadImageCommandRequest : IRequest<Result<ImageUploadResult>>, IIdempotentCommand
{
    public required FileUploadDto File { get; init; }
    public bool GenerateThumbnail { get; init; } = true;

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "media.upload-image";
    public string? CustomRequestHash { get; set; }
}
