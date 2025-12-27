using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.CategoryFeature.Commands.CreateCategoryCommand;

public class CreateCategoryCommandResponse
{
    public Result<Guid> Result { get; set; } = null!;
}
