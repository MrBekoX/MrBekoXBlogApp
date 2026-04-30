using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.MediaFeature.Commands.DeleteMediaCommand;

public class DeleteMediaCommandResponse
{
    public Result Result { get; set; } = null!;
}
