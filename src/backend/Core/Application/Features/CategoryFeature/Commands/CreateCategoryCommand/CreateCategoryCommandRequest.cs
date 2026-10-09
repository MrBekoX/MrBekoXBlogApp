using BlogApp.Core.Application.Common.Interfaces;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.CategoryFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.CategoryFeature.Commands.CreateCategoryCommand;

public class CreateCategoryCommandRequest : IRequest<Result<Guid>>, IIdempotentCommand
{
    public CreateCategoryCommandDto? CreateCategoryCommandRequestDto { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "categories.create";
}
