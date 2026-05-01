using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.MediaFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.MediaFeature.Commands.UploadImageCommand;

public class UploadImageCommandRequest : IRequest<Result<ImageUploadResult>>, IIdempotentCommand
{
    public required FileUploadDto File { get; init; }
    public bool GenerateThumbnail { get; init; } = true;

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "media.upload-image";
    public string? CustomRequestHash { get; set; }
}
