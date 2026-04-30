namespace BlogApp.Server.Application.Features.MediaFeature.DTOs;

public record FileUploadDto
{
    public required Stream Stream { get; init; }
    public required string FileName { get; init; }
    public required string ContentType { get; init; }
    public required long Length { get; init; }
}
