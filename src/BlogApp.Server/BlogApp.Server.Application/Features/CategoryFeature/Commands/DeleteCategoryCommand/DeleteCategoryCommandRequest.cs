using BlogApp.Server.Application.Common.Interfaces;
using MediatR;

namespace BlogApp.Server.Application.Features.CategoryFeature.Commands.DeleteCategoryCommand;

public class DeleteCategoryCommandRequest : IRequest<DeleteCategoryCommandResponse>, IIdempotentCommand
{
    public Guid Id { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "categories.delete";
}

