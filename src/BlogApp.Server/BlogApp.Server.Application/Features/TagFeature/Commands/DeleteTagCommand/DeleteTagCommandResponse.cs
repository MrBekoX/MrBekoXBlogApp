using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.TagFeature.Commands.DeleteTagCommand;

public class DeleteTagCommandResponse
{
    public Result Result { get; set; } = null!;
}
