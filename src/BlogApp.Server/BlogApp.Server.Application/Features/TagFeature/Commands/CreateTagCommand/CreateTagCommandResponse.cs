using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.TagFeature.Commands.CreateTagCommand;

public class CreateTagCommandResponse
{
    public Result<Guid> Result { get; set; } = null!;
}
