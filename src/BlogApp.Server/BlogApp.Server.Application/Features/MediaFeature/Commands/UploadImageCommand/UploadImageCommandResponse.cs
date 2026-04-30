using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.MediaFeature.Commands.UploadImageCommand;

public class UploadImageCommandResponse
{
    public Result<ImageUploadResult> Result { get; set; } = null!;
}
