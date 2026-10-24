using System.Security.Cryptography;
using System.Text;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Common.Utilities;
using BlogApp.Core.Application.Features.MediaFeature.Commands.DeleteMediaCommand;
using BlogApp.Core.Application.Features.MediaFeature.Commands.UploadImageCommand;
using BlogApp.Core.Application.Features.MediaFeature.Commands.UploadImagesCommand;
using BlogApp.Core.Application.Features.MediaFeature.DTOs;
using BlogApp.Presentation.Api.Filters;
using BlogApp.Presentation.Api.Helpers;
using MediatR;

namespace BlogApp.Presentation.Api.Endpoints;

public static class MediaEndpoints
{
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
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            if (file == null || file.Length == 0)
                return Results.BadRequest(ApiResponse<ImageUploadResult>.FailureResult("No file uploaded"));

            if (file.Length < 0 || file.Length > ImageValidation.MaxFileSize)
                return Results.BadRequest(ApiResponse<ImageUploadResult>.FailureResult("File too large. Maximum size: 10MB"));

            // Own one bounded, seekable buffer through hashing and command execution.
            await using var memoryStream = await BufferFileAsync(file, cancellationToken);
            var fileDto = new FileUploadDto
            {
                Stream = memoryStream,
                FileName = file.FileName,
                ContentType = file.ContentType,
                Length = memoryStream.Length
            };

            var response = await mediator.Send(new UploadImageCommandRequest
            {
                File = fileDto,
                GenerateThumbnail = generateThumbnail ?? true,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty,
                CustomRequestHash = await BuildUploadRequestHashAsync([fileDto], generateThumbnail, cancellationToken)
            }, cancellationToken);

            if (!response.IsSuccess)
                return response.ToHttpResult();

            return Results.Ok(ApiResponse<ImageUploadResult>.SuccessResult(response.Value!, "Image uploaded successfully"));
        })
        .WithName("UploadImage")
        .WithDescription("Upload an image")
        .WithFormOptions(multipartBodyLengthLimit: ImageValidation.MaxFileSize)
        .RequireRateLimiting("image-upload")
        .ValidateAntiforgery()
        .Produces<ApiResponse<ImageUploadResult>>(200)
        .Produces(400)
        .Produces(413)
        .Produces(429);

        // POST /api/media/upload/images
        group.MapPost("/upload/images", async (
            IFormFileCollection files,
            HttpContext httpContext,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            if (files == null || files.Count == 0)
                return Results.BadRequest(ApiResponse<UploadImagesResultDto>.FailureResult("No files uploaded"));

            if (files.Count > ImageValidation.MaxBatchSize)
                return Results.BadRequest(ApiResponse<UploadImagesResultDto>.FailureResult("Maximum 10 files at once"));

            long totalLength = 0;
            foreach (var file in files)
            {
                if (file.Length < 0 || file.Length > ImageValidation.MaxFileSize)
                    return Results.BadRequest(ApiResponse<UploadImagesResultDto>.FailureResult("File too large. Maximum size: 10MB"));
                if (file.Length > ImageValidation.MaxBatchFileSize - totalLength)
                    return Results.BadRequest(ApiResponse<UploadImagesResultDto>.FailureResult("Total upload size is too large"));
                totalLength += file.Length;
            }

            var fileDtos = new List<FileUploadDto>();
            var memoryStreams = new List<MemoryStream>();

            try
            {
                foreach (var file in files)
                {
                    var memoryStream = await BufferFileAsync(file, cancellationToken);
                    memoryStreams.Add(memoryStream);
                    fileDtos.Add(new FileUploadDto
                    {
                        Stream = memoryStream,
                        FileName = file.FileName,
                        ContentType = file.ContentType,
                        Length = memoryStream.Length
                    });
                }

                var response = await mediator.Send(new UploadImagesCommandRequest
                {
                    Files = fileDtos,
                    OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty,
                    CustomRequestHash = await BuildUploadRequestHashAsync(fileDtos, null, cancellationToken)
                }, cancellationToken);

                if (!response.IsSuccess)
                    return response.ToHttpResult();

                return Results.Ok(ApiResponse<UploadImagesResultDto>.SuccessResult(response.Value!, response.Value!.Message));
            }
            finally
            {
                foreach (var stream in memoryStreams)
                    await stream.DisposeAsync();
            }
        })
        .WithName("UploadImages")
        .WithDescription("Upload multiple images")
        .WithFormOptions(multipartBodyLengthLimit: ImageValidation.MaxFileSize)
        .RequireRateLimiting("image-upload")
        .ValidateAntiforgery()
        .Produces<ApiResponse<UploadImagesResultDto>>(200)
        .Produces(400)
        .Produces(413)
        .Produces(429);

        // DELETE /api/media
        group.MapDelete("/", async (
            string url,
            HttpContext httpContext,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new DeleteMediaCommandRequest
            {
                Url = url,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            if (!response.IsSuccess)
                return response.ToHttpResult();

            return Results.NoContent();
        })
        .WithName("DeleteFile")
        .WithDescription("Delete an uploaded file")
        .ValidateAntiforgery()
        .Produces(204)
        .Produces(404);

        return app;
    }

    private static async Task<MemoryStream> BufferFileAsync(IFormFile file, CancellationToken cancellationToken)
    {
        var initialCapacity = file.Length is >= 0 and <= ImageValidation.MaxFileSize ? (int)file.Length : 0;
        var memoryStream = new MemoryStream(initialCapacity);
        try
        {
            await using var source = file.OpenReadStream();
            var buffer = new byte[81920];
            while (true)
            {
                cancellationToken.ThrowIfCancellationRequested();
                // Read at most one byte beyond the limit, including when Length is inaccurate.
                var count = (int)Math.Min(buffer.Length, ImageValidation.MaxFileSize - memoryStream.Length + 1);
                var bytesRead = await source.ReadAsync(buffer.AsMemory(0, count), cancellationToken);
                if (bytesRead == 0)
                    break;
                if (bytesRead > ImageValidation.MaxFileSize - memoryStream.Length)
                    throw new BadHttpRequestException("File too large. Maximum size: 10MB", StatusCodes.Status413PayloadTooLarge);
                await memoryStream.WriteAsync(buffer.AsMemory(0, bytesRead), cancellationToken);
            }

            memoryStream.Position = 0;
            return memoryStream;
        }
        catch
        {
            await memoryStream.DisposeAsync();
            throw;
        }
    }

    private static async Task<string> BuildUploadRequestHashAsync(
        IReadOnlyCollection<FileUploadDto> files,
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

            var stream = file.Stream;
            var originalPosition = stream.Position;
            var buffer = new byte[81920];
            try
            {
                stream.Position = 0;
                while (true)
                {
                    var bytesRead = await stream.ReadAsync(buffer.AsMemory(0, buffer.Length), cancellationToken);
                    if (bytesRead == 0) break;
                    hasher.AppendData(buffer, 0, bytesRead);
                }
            }
            finally
            {
                stream.Position = originalPosition;
            }
        }

        return Convert.ToHexString(hasher.GetHashAndReset());
    }

    private static void AppendHashText(IncrementalHash hasher, string value)
    {
        var bytes = Encoding.UTF8.GetBytes(value);
        hasher.AppendData(bytes);
    }
}
