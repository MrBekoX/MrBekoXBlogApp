using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Common.Utilities;
using BlogApp.Core.Application.Features.MediaFeature.DTOs;
using MediatR;
using Microsoft.Extensions.Logging;

namespace BlogApp.Core.Application.Features.MediaFeature.Commands.UploadImagesCommand;

public class UploadImagesCommandHandler(
    IFileStorageService fileStorageService,
    ILogger<UploadImagesCommandHandler> logger) : IRequestHandler<UploadImagesCommandRequest, Result<UploadImagesResultDto>>
{
    public async Task<Result<UploadImagesResultDto>> Handle(
        UploadImagesCommandRequest request, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (request.Files.Count == 0)
            return Result<UploadImagesResultDto>.Failure(Error.Validation("No files uploaded"));

        if (request.Files.Count > ImageValidation.MaxBatchSize)
            return Result<UploadImagesResultDto>.Failure(Error.Validation("Maximum 10 files at once"));

        long totalLength = 0;
        foreach (var file in request.Files)
        {
            if (file.Length < 0 || file.Length > ImageValidation.MaxBatchFileSize - totalLength)
                return Result<UploadImagesResultDto>.Failure(Error.Validation("Total upload size is too large"));
            totalLength += file.Length;
        }

        var results = new List<ImageUploadResult>();
        var errors = new List<string>();

        foreach (var file in request.Files)
        {
            cancellationToken.ThrowIfCancellationRequested();
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
                var result = await fileStorageService.UploadImageAsync(file.Stream, safeFileName, cancellationToken: cancellationToken).ConfigureAwait(false);
                results.Add(result);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                logger.LogError(ex, "Error uploading image {FileName}", file.FileName);
                errors.Add($"{file.FileName}: Upload failed");
            }
        }

        var message = errors.Count > 0
            ? $"Uploaded {results.Count} files. Errors: {string.Join(", ", errors)}"
            : $"Uploaded {results.Count} files successfully";

        return Result<UploadImagesResultDto>.Success(new UploadImagesResultDto
        {
            Uploaded = results,
            Errors = errors,
            Message = message
        });
    }
}
