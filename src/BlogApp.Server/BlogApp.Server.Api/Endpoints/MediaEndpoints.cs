using System.Security.Cryptography;
using System.Text;
using BlogApp.Server.Application.Common.Interfaces.Data;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Api.Endpoints;

public static class MediaEndpoints
{
    private static readonly string[] AllowedImageTypes = { "image/jpeg", "image/png", "image/gif", "image/webp" };
    private const long MaxFileSize = 10 * 1024 * 1024; // 10MB

    public static IEndpointRouteBuilder RegisterMediaEndpoints(this IEndpointRouteBuilder app)
    {
        var versionedGroup = app.NewVersionedApi("Media");
        var group = versionedGroup.MapGroup("/api/v{version:apiVersion}/media")
            .HasApiVersion(1.0)
            .WithTags("Media")
            .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"));

        // POST /api/media/upload/image
        group.MapPost("/upload/image", async (
            IFormFile file,
            bool? generateThumbnail,
            HttpContext httpContext,
            IFileStorageService fileStorageService,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            ILogger<Program> logger,
            CancellationToken cancellationToken) =>
        {
            if (file == null || file.Length == 0)
                return Results.BadRequest(ApiResponse<ImageUploadResult>.FailureResult("No file uploaded"));

            var requestHash = await BuildUploadRequestHashAsync(new[] { file }, generateThumbnail, cancellationToken);
            var requestPayload = new
            {
                file.FileName,
                file.Length,
                file.ContentType,
                GenerateThumbnail = generateThumbnail ?? true
            };

            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                httpContext, "UploadImage", requestPayload, unitOfWork, idempotencyService, currentUserService, cancellationToken,
                requireIdempotencyKey: true,
                requestHash: requestHash);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            if (!AllowedImageTypes.Contains(file.ContentType.ToLowerInvariant()))
            {
                await scope.FailAndCommitAsync(
                    "invalid_file_type", "Invalid file type. Allowed: JPEG, PNG, GIF, WebP", idempotencyService, cancellationToken);
                return Results.BadRequest(ApiResponse<ImageUploadResult>.FailureResult("Invalid file type. Allowed: JPEG, PNG, GIF, WebP"));
            }

            if (file.Length > MaxFileSize)
            {
                var message = $"File too large. Maximum size: {MaxFileSize / 1024 / 1024}MB";
                await scope.FailAndCommitAsync(
                    "file_too_large", message, idempotencyService, cancellationToken);
                return Results.BadRequest(ApiResponse<ImageUploadResult>.FailureResult(message));
            }

            try
            {
                await using var stream = file.OpenReadStream();

                // SECURITY: Validate magic bytes to prevent fake image uploads
                if (!IsValidImageFile(stream, file.ContentType))
                {
                    await scope.FailAndCommitAsync(
                        "invalid_image_format", "Invalid image file format", idempotencyService, cancellationToken);
                    return Results.BadRequest(ApiResponse<ImageUploadResult>.FailureResult("Invalid image file format"));
                }

                // SECURITY: Sanitize filename to prevent path traversal
                var safeFileName = SanitizeFileName(file.FileName);

                var options = new ImageUploadOptions
                {
                    GenerateThumbnail = generateThumbnail ?? true,
                    ConvertToWebP = true,
                    Quality = 85
                };

                var result = await fileStorageService.UploadImageAsync(stream, safeFileName, options);
                var response = ApiResponse<ImageUploadResult>.SuccessResult(result, "Image uploaded successfully");
                await scope.CompleteAndCommitAsync(
                    StatusCodes.Status200OK, response, idempotencyService, cancellationToken);

                return Results.Ok(response);
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Error uploading image");
                return Results.BadRequest(ApiResponse<ImageUploadResult>.FailureResult("Error uploading image"));
            }
        })
        .WithName("UploadImage")
        .WithDescription("Upload an image")
        .Produces<ApiResponse<ImageUploadResult>>(200)
        .Produces(400)
        .Produces(StatusCodes.Status409Conflict);

        // POST /api/media/upload/images
        group.MapPost("/upload/images", async (
            IFormFileCollection files,
            HttpContext httpContext,
            IFileStorageService fileStorageService,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            ILogger<Program> logger,
            CancellationToken cancellationToken) =>
        {
            if (files == null || files.Count == 0)
                return Results.BadRequest(ApiResponse<List<ImageUploadResult>>.FailureResult("No files uploaded"));

            var requestHash = await BuildUploadRequestHashAsync(files, null, cancellationToken);
            var requestPayload = new
            {
                FileCount = files.Count,
                Files = files.Select(file => new
                {
                    file.FileName,
                    file.Length,
                    file.ContentType
                }).ToArray()
            };

            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                httpContext, "UploadImages", requestPayload, unitOfWork, idempotencyService, currentUserService, cancellationToken,
                requireIdempotencyKey: true,
                requestHash: requestHash);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            if (files.Count > 10)
            {
                await scope.FailAndCommitAsync(
                    "too_many_files", "Maximum 10 files at once", idempotencyService, cancellationToken);
                return Results.BadRequest(ApiResponse<List<ImageUploadResult>>.FailureResult("Maximum 10 files at once"));
            }

            var results = new List<ImageUploadResult>();
            var errors = new List<string>();

            foreach (var file in files)
            {
                if (!AllowedImageTypes.Contains(file.ContentType.ToLowerInvariant()))
                {
                    errors.Add($"{file.FileName}: Invalid file type");
                    continue;
                }

                if (file.Length > MaxFileSize)
                {
                    errors.Add($"{file.FileName}: File too large");
                    continue;
                }

                try
                {
                    await using var stream = file.OpenReadStream();

                    // SECURITY: Validate magic bytes
                    if (!IsValidImageFile(stream, file.ContentType))
                    {
                        errors.Add($"{file.FileName}: Invalid image file format");
                        continue;
                    }

                    // SECURITY: Sanitize filename
                    var safeFileName = SanitizeFileName(file.FileName);

                    var result = await fileStorageService.UploadImageAsync(stream, safeFileName);
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

            var response = ApiResponse<List<ImageUploadResult>>.SuccessResult(results, message);
            await scope.CompleteAndCommitAsync(
                StatusCodes.Status200OK, response, idempotencyService, cancellationToken);

            return Results.Ok(response);
        })
        .WithName("UploadImages")
        .WithDescription("Upload multiple images")
        .Produces<ApiResponse<List<ImageUploadResult>>>(200)
        .Produces(400)
        .Produces(StatusCodes.Status409Conflict);

        // DELETE /api/media
        group.MapDelete("/", async (
            string url,
            HttpContext httpContext,
            IFileStorageService fileStorageService,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            CancellationToken cancellationToken) =>
        {
            if (string.IsNullOrEmpty(url))
                return Results.BadRequest(ApiResponse<object>.FailureResult("URL is required"));

            var requestPayload = new { Url = url };
            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                httpContext, "DeleteFile", requestPayload, unitOfWork, idempotencyService, currentUserService, cancellationToken,
                requireIdempotencyKey: true);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            var deleted = await fileStorageService.DeleteAsync(url);

            if (!deleted)
            {
                await scope.FailAndCommitAsync(
                    "file_not_found", "File not found", idempotencyService, cancellationToken);
                return Results.NotFound(ApiResponse<object>.FailureResult("File not found"));
            }

            var response = ApiResponse<object>.SuccessResult(new { url }, "File deleted successfully");
            await scope.CompleteAndCommitAsync(
                StatusCodes.Status204NoContent, response, idempotencyService, cancellationToken);

            return Results.NoContent();
        })
        .WithName("DeleteFile")
        .WithDescription("Delete an uploaded file")
        .Produces(204)
        .Produces(404)
        .Produces(StatusCodes.Status409Conflict);

        return app;
    }

    private static async Task<string> BuildUploadRequestHashAsync(
        IReadOnlyCollection<IFormFile> files,
        bool? generateThumbnail,
        CancellationToken cancellationToken)
    {
        using var hasher = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        AppendHashText(hasher, $"generateThumbnail={generateThumbnail?.ToString() ?? "null"}");

        foreach (var file in files)
        {
            AppendHashText(hasher, file.FileName);
            AppendHashText(hasher, file.ContentType);
            AppendHashText(hasher, file.Length.ToString());

            await using var stream = file.OpenReadStream();
            var buffer = new byte[81920];
            while (true)
            {
                var bytesRead = await stream.ReadAsync(buffer.AsMemory(0, buffer.Length), cancellationToken);
                if (bytesRead == 0)
                {
                    break;
                }

                hasher.AppendData(buffer, 0, bytesRead);
            }
        }

        return Convert.ToHexString(hasher.GetHashAndReset());
    }

    private static void AppendHashText(IncrementalHash hasher, string value)
    {
        var bytes = Encoding.UTF8.GetBytes(value);
        hasher.AppendData(bytes);
    }

    /// <summary>
    /// SECURITY: Sanitizes filename to prevent path traversal attacks
    /// </summary>
    private static string SanitizeFileName(string fileName)
    {
        if (string.IsNullOrWhiteSpace(fileName))
            throw new ArgumentException("Filename cannot be empty", nameof(fileName));

        // Remove path components - only keep filename
        var sanitized = Path.GetFileName(fileName);
        
        // Remove invalid filename characters
        var invalidChars = Path.GetInvalidFileNameChars();
        sanitized = string.Join("_", sanitized.Split(invalidChars, StringSplitOptions.RemoveEmptyEntries));
        
        // Reject filenames that are only dots or empty after sanitization
        if (string.IsNullOrWhiteSpace(sanitized) || sanitized.All(c => c == '.'))
            throw new ArgumentException("Invalid filename", nameof(fileName));
        
        return sanitized;
    }

    /// <summary>
    /// SECURITY: Validates file content by checking magic bytes
    /// Prevents attackers from uploading malicious files with fake extensions
    /// </summary>
    private static bool IsValidImageFile(Stream stream, string contentType)
    {
        stream.Position = 0;
        var header = new byte[12];
        var bytesRead = stream.Read(header, 0, 12);
        stream.Position = 0;

        if (bytesRead < 4)
            return false;

        // Check magic bytes for each image type
        var lowerContentType = contentType.ToLowerInvariant();
        
        if (lowerContentType.Contains("jpeg") || lowerContentType.Contains("jpg"))
        {
            // JPEG: FF D8 FF
            return header[0] == 0xFF && header[1] == 0xD8 && header[2] == 0xFF;
        }
        else if (lowerContentType.Contains("png"))
        {
            // PNG: 89 50 4E 47
            return header[0] == 0x89 && header[1] == 0x50 && header[2] == 0x4E && header[3] == 0x47;
        }
        else if (lowerContentType.Contains("gif"))
        {
            // GIF: 47 49 46 (GIF87a or GIF89a)
            return header[0] == 0x47 && header[1] == 0x49 && header[2] == 0x46;
        }
        else if (lowerContentType.Contains("webp"))
        {
            // WebP: RIFF....WEBP (52 49 46 46 at 0-3, 57 45 42 50 at 8-11)
            if (bytesRead < 12)
                return false;
            return header[0] == 0x52 && header[1] == 0x49 && header[2] == 0x46 && header[3] == 0x46 &&
                   header[8] == 0x57 && header[9] == 0x45 && header[10] == 0x42 && header[11] == 0x50;
        }
        
        return false;
    }
}
