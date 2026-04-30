using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Features.CategoryFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.CategoryFeature.Commands.CreateCategoryCommand;

public class CreateCategoryCommandRequest : IRequest<CreateCategoryCommandResponse>, IIdempotentCommand
{
    public CreateCategoryCommandDto? CreateCategoryCommandRequestDto { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "categories.create";
}

