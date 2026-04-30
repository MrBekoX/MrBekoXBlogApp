using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.MediaFeature.Commands.UploadImagesCommand;

public class UploadImagesCommandResponse
{
    public Result<List<ImageUploadResult>> Result { get; set; } = null!;
    public List<string> Errors { get; set; } = [];
    public string Message { get; set; } = string.Empty;
}
