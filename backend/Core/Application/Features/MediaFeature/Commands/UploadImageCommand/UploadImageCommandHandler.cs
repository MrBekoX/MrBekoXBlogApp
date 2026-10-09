using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Common.Utilities;
using MediatR;
using Microsoft.Extensions.Logging;

namespace BlogApp.Core.Application.Features.MediaFeature.Commands.UploadImageCommand;

public class UploadImageCommandHandler(
    IFileStorageService fileStorageService,
    ILogger<UploadImageCommandHandler> logger) : IRequestHandler<UploadImageCommandRequest, Result<ImageUploadResult>>
{
    public async Task<Result<ImageUploadResult>> Handle(
        UploadImageCommandRequest request, CancellationToken cancellationToken)
    {
        var file = request.File;

        if (file.Length == 0)
            return Result<ImageUploadResult>.Failure(Error.Validation("No file uploaded"));

        if (!ImageValidation.AllowedImageTypes.Contains(file.ContentType.ToLowerInvariant()))
            return Result<ImageUploadResult>.Failure(Error.Validation("Invalid file type. Allowed: JPEG, PNG, GIF, WebP"));

        if (file.Length > ImageValidation.MaxFileSize)
            return Result<ImageUploadResult>.Failure(Error.Validation($"File too large. Maximum size: {ImageValidation.MaxFileSize / 1024 / 1024}MB"));

        if (!ImageValidation.IsValidImageFile(file.Stream, file.ContentType))
            return Result<ImageUploadResult>.Failure(Error.Validation("Invalid image file format"));

        var safeFileName = ImageValidation.SanitizeFileName(file.FileName);

        var options = new ImageUploadOptions
        {
            GenerateThumbnail = request.GenerateThumbnail,
            ConvertToWebP = true,
            Quality = 85
        };

        // IO failures are infra exceptions — let ExceptionHandlingMiddleware handle them
        var result = await fileStorageService.UploadImageAsync(file.Stream, safeFileName, options, cancellationToken).ConfigureAwait(false);

        logger.LogInformation("Image uploaded successfully: {FileName}", safeFileName);

        return Result<ImageUploadResult>.Success(result);
    }
}
