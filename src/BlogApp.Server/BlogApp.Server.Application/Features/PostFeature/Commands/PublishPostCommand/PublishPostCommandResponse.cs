using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.PublishPostCommand;

public class PublishPostCommandResponse
{
    public Result Result { get; set; } = null!;
}

public class UnpublishPostCommandResponse
{
    public Result Result { get; set; } = null!;
}

