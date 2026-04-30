using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Common.Utilities;
using MediatR;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Application.Features.MediaFeature.Commands.UploadImageCommand;

public class UploadImageCommandHandler(
    IFileStorageService fileStorageService,
    ILogger<UploadImageCommandHandler> logger) : IRequestHandler<UploadImageCommandRequest, UploadImageCommandResponse>
{
    public async Task<UploadImageCommandResponse> Handle(
        UploadImageCommandRequest request, CancellationToken cancellationToken)
    {
        var file = request.File;

        if (file.Length == 0)
            return new UploadImageCommandResponse
            {
                Result = Result<ImageUploadResult>.Failure("No file uploaded")
            };

        if (!ImageValidation.AllowedImageTypes.Contains(file.ContentType.ToLowerInvariant()))
            return new UploadImageCommandResponse
            {
                Result = Result<ImageUploadResult>.Failure("Invalid file type. Allowed: JPEG, PNG, GIF, WebP")
            };

        if (file.Length > ImageValidation.MaxFileSize)
            return new UploadImageCommandResponse
            {
                Result = Result<ImageUploadResult>.Failure($"File too large. Maximum size: {ImageValidation.MaxFileSize / 1024 / 1024}MB")
            };

        if (!ImageValidation.IsValidImageFile(file.Stream, file.ContentType))
            return new UploadImageCommandResponse
            {
                Result = Result<ImageUploadResult>.Failure("Invalid image file format")
            };

        try
        {
            var safeFileName = ImageValidation.SanitizeFileName(file.FileName);

            var options = new ImageUploadOptions
            {
                GenerateThumbnail = request.GenerateThumbnail,
                ConvertToWebP = true,
                Quality = 85
            };

            var result = await fileStorageService.UploadImageAsync(file.Stream, safeFileName, options);

            return new UploadImageCommandResponse
            {
                Result = Result<ImageUploadResult>.Success(result)
            };
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Error uploading image");
            return new UploadImageCommandResponse
            {
                Result = Result<ImageUploadResult>.Failure("Error uploading image")
            };
        }
    }
}
