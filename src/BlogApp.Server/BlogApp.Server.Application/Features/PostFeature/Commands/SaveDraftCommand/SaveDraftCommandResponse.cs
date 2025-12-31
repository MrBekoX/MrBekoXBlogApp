using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.PostFeature.Commands.SaveDraftCommand;

public class SaveDraftCommandResponse
{
    public Result<Guid> Result { get; set; } = null!;
}

