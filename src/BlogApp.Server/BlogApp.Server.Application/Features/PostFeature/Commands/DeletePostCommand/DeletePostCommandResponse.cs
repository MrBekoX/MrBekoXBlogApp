using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.DeletePostCommand;

public class DeletePostCommandResponse
{
    public Result Result { get; set; } = null!;
}

