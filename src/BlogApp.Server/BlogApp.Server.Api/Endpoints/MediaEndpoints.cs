using System.Security.Cryptography;
using System.Text;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.MediaFeature.Commands.DeleteMediaCommand;
using BlogApp.Server.Application.Features.MediaFeature.Commands.UploadImageCommand;
using BlogApp.Server.Application.Features.MediaFeature.Commands.UploadImagesCommand;
using BlogApp.Server.Application.Features.MediaFeature.DTOs;
using BlogApp.Server.Api.Filters;
using BlogApp.Server.Api.Helpers;
using MediatR;

namespace BlogApp.Server.Api.Endpoints;

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

            // Copy to MemoryStream — IFormFile stream is non-seekable (ReferenceReadStream)
            // but ImageValidation.IsValidImageFile needs seek support for magic byte checking
            var memoryStream = new MemoryStream();
            await using (var formStream = file.OpenReadStream())
            {
                await formStream.CopyToAsync(memoryStream, cancellationToken);
            }
            memoryStream.Position = 0;

            var response = await mediator.Send(new UploadImageCommandRequest
            {
                File = new FileUploadDto
                {
                    Stream = memoryStream,
                    FileName = file.FileName,
                    ContentType = file.ContentType,
                    Length = file.Length
                },
                GenerateThumbnail = generateThumbnail ?? true,
                OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty,
                CustomRequestHash = await BuildUploadRequestHashAsync([file], generateThumbnail, cancellationToken)
            }, cancellationToken);

            if (!response.IsSuccess)
                return response.ToHttpResult();

            return Results.Ok(ApiResponse<ImageUploadResult>.SuccessResult(response.Value!, "Image uploaded successfully"));
        })
        .WithName("UploadImage")
        .WithDescription("Upload an image")
        .ValidateAntiforgery()
        .Produces<ApiResponse<ImageUploadResult>>(200)
        .Produces(400);

        // POST /api/media/upload/images
        group.MapPost("/upload/images", async (
            IFormFileCollection files,
            HttpContext httpContext,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            if (files == null || files.Count == 0)
                return Results.BadRequest(ApiResponse<UploadImagesResultDto>.FailureResult("No files uploaded"));

            var fileDtos = new List<FileUploadDto>();
            var memoryStreams = new List<MemoryStream>();

            foreach (var file in files)
            {
                var memoryStream = new MemoryStream();
                await using (var formStream = file.OpenReadStream())
                {
                    await formStream.CopyToAsync(memoryStream, cancellationToken);
                }
                memoryStream.Position = 0;
                memoryStreams.Add(memoryStream);
                fileDtos.Add(new FileUploadDto
                {
                    Stream = memoryStream,
                    FileName = file.FileName,
                    ContentType = file.ContentType,
                    Length = file.Length
                });
            }

            try
            {
                var response = await mediator.Send(new UploadImagesCommandRequest
                {
                    Files = fileDtos,
                    OperationId = httpContext.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty,
                    CustomRequestHash = await BuildUploadRequestHashAsync(files, null, cancellationToken)
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
        .ValidateAntiforgery()
        .Produces<ApiResponse<UploadImagesResultDto>>(200)
        .Produces(400);

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
                if (bytesRead == 0) break;
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
}
