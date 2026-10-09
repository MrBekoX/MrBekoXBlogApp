using BlogApp.Core.Application.Common.Interfaces;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.CategoryFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.CategoryFeature.Commands.UpdateCategoryCommand;

public class UpdateCategoryCommandRequest : IRequest<Result<Unit>>, IIdempotentCommand
{
    public UpdateCategoryCommandDto? UpdateCategoryCommandRequestDto { get; set; }

    public string OperationId { get; set; } = string.Empty;
    public string IdempotencyEndpointName => "categories.update";
}
