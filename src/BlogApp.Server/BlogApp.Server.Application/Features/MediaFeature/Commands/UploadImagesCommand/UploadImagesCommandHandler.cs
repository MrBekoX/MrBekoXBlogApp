using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Common.Utilities;
using MediatR;
using Microsoft.Extensions.Logging;

namespace BlogApp.Server.Application.Features.MediaFeature.Commands.UploadImagesCommand;

public class UploadImagesCommandHandler(
    IFileStorageService fileStorageService,
    ILogger<UploadImagesCommandHandler> logger) : IRequestHandler<UploadImagesCommandRequest, UploadImagesCommandResponse>
{
    public async Task<UploadImagesCommandResponse> Handle(
        UploadImagesCommandRequest request, CancellationToken cancellationToken)
    {
        if (request.Files.Count == 0)
            return new UploadImagesCommandResponse
            {
                Result = Result<List<ImageUploadResult>>.Failure("No files uploaded")
            };

        if (request.Files.Count > 10)
            return new UploadImagesCommandResponse
            {
                Result = Result<List<ImageUploadResult>>.Failure("Maximum 10 files at once")
            };

        var results = new List<ImageUploadResult>();
        var errors = new List<string>();

        foreach (var file in request.Files)
        {
            if (!ImageValidation.AllowedImageTypes.Contains(file.ContentType.ToLowerInvariant()))
            {
                errors.Add($"{file.FileName}: Invalid file type");
                continue;
            }

            if (file.Length > ImageValidation.MaxFileSize)
            {
                errors.Add($"{file.FileName}: File too large");
                continue;
            }

            if (!ImageValidation.IsValidImageFile(file.Stream, file.ContentType))
            {
                errors.Add($"{file.FileName}: Invalid image file format");
                continue;
            }

            try
            {
                var safeFileName = ImageValidation.SanitizeFileName(file.FileName);
                var result = await fileStorageService.UploadImageAsync(file.Stream, safeFileName);
                results.Add(result);
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Error uploading image {FileName}", file.FileName);
                errors.Add($"{file.FileName}: Upload failed");
            }
        }

        var message = errors.Count > 0
            ? $"Uploaded {results.Count} files. Errors: {string.Join(", ", errors)}"
            : $"Uploaded {results.Count} files successfully";

        return new UploadImagesCommandResponse
        {
            Result = Result<List<ImageUploadResult>>.Success(results),
            Errors = errors,
            Message = message
        };
    }
}
