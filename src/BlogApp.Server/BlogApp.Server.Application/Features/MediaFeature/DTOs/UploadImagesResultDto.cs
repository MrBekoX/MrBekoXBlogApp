using BlogApp.Server.Application.Common.Interfaces.Services;

namespace BlogApp.Server.Application.Features.MediaFeature.DTOs;

/// <summary>
/// Carries the result of a batch image upload including per-file errors (partial success).
/// </summary>
public class UploadImagesResultDto
{
    public IReadOnlyList<ImageUploadResult> Uploaded { get; init; } = [];
    public IReadOnlyList<string> Errors { get; init; } = [];
    public string Message { get; init; } = string.Empty;
}
