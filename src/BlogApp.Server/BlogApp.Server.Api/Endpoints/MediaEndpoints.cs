using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Api.Endpoints;

public static class MediaEndpoints
{
    private static readonly string[] AllowedImageTypes = { "image/jpeg", "image/png", "image/gif", "image/webp" };
    private const long MaxFileSize = 10 * 1024 * 1024; // 10MB

    public static IEndpointRouteBuilder RegisterMediaEndpoints(this IEndpointRouteBuilder app)
    {
        var group = app.MapGroup("/api/media")
            .WithTags("Media")
            .RequireAuthorization(policy => policy.RequireRole("Admin", "Editor", "Author"));

        // POST /api/media/upload/image
        group.MapPost("/upload/image", async (
            IFormFile file,
            bool generateThumbnail,
            IFileStorageService fileStorageService,
            ILogger<Program> logger,
            CancellationToken cancellationToken) =>
        {
            if (file == null || file.Length == 0)
                return Results.BadRequest(ApiResponse<ImageUploadResult>.FailureResult("No file uploaded"));

            if (!AllowedImageTypes.Contains(file.ContentType.ToLowerInvariant()))
                return Results.BadRequest(ApiResponse<ImageUploadResult>.FailureResult("Invalid file type. Allowed: JPEG, PNG, GIF, WebP"));

            if (file.Length > MaxFileSize)
                return Results.BadRequest(ApiResponse<ImageUploadResult>.FailureResult($"File too large. Maximum size: {MaxFileSize / 1024 / 1024}MB"));

            try
            {
                await using var stream = file.OpenReadStream();

                var options = new ImageUploadOptions
                {
                    GenerateThumbnail = generateThumbnail,
                    ConvertToWebP = true,
                    Quality = 85
                };

                var result = await fileStorageService.UploadImageAsync(stream, file.FileName, options);

                return Results.Ok(ApiResponse<ImageUploadResult>.SuccessResult(result, "Image uploaded successfully"));
            }
            catch (Exception ex)
            {
                logger.LogError(ex, "Error uploading image");
                return Results.BadRequest(ApiResponse<ImageUploadResult>.FailureResult("Error uploading image"));
            }
        })
        .WithName("UploadImage")
        .WithDescription("Upload an image")
        .DisableAntiforgery()
        .Produces<ApiResponse<ImageUploadResult>>(200)
        .Produces(400);

        // POST /api/media/upload/images
        group.MapPost("/upload/images", async (
            IFormFileCollection files,
            IFileStorageService fileStorageService,
            ILogger<Program> logger,
            CancellationToken cancellationToken) =>
        {
            if (files == null || files.Count == 0)
                return Results.BadRequest(ApiResponse<List<ImageUploadResult>>.FailureResult("No files uploaded"));

            if (files.Count > 10)
                return Results.BadRequest(ApiResponse<List<ImageUploadResult>>.FailureResult("Maximum 10 files at once"));

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
                    var result = await fileStorageService.UploadImageAsync(stream, file.FileName);
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

            return Results.Ok(ApiResponse<List<ImageUploadResult>>.SuccessResult(results, message));
        })
        .WithName("UploadImages")
        .WithDescription("Upload multiple images")
        .DisableAntiforgery()
        .Produces<ApiResponse<List<ImageUploadResult>>>(200)
        .Produces(400);

        // DELETE /api/media
        group.MapDelete("/", async (
            string url,
            IFileStorageService fileStorageService,
            CancellationToken cancellationToken) =>
        {
            if (string.IsNullOrEmpty(url))
                return Results.BadRequest(ApiResponse<object>.FailureResult("URL is required"));

            var deleted = await fileStorageService.DeleteAsync(url);

            if (!deleted)
                return Results.NotFound(ApiResponse<object>.FailureResult("File not found"));

            return Results.NoContent();
        })
        .WithName("DeleteFile")
        .WithDescription("Delete an uploaded file")
        .Produces(204)
        .Produces(404);

        return app;
    }
}
