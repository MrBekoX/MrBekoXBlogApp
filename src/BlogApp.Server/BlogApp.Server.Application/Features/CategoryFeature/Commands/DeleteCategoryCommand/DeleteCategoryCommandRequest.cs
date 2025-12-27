using MediatR;

namespace BlogApp.Server.Application.Features.CategoryFeature.Commands.DeleteCategoryCommand;

public class DeleteCategoryCommandRequest : IRequest<DeleteCategoryCommandResponse>
{
    public Guid Id { get; set; }
}
