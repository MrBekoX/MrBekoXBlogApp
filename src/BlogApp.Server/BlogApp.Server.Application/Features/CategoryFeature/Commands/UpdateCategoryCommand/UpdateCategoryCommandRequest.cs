using BlogApp.Server.Application.Features.CategoryFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.CategoryFeature.Commands.UpdateCategoryCommand;

public class UpdateCategoryCommandRequest : IRequest<UpdateCategoryCommandResponse>
{
    public UpdateCategoryCommandDto? UpdateCategoryCommandRequestDto { get; set; }
}
