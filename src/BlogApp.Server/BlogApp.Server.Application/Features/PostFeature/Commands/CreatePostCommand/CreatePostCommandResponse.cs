using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.CreatePostCommand;

public class CreatePostCommandResponse
{
    public Result<Guid> Result { get; set; } = null!;
}
