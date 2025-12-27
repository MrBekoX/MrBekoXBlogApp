using BlogApp.Server.Application.Features.CategoryFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.CategoryFeature.Commands.CreateCategoryCommand;

public class CreateCategoryCommandRequest : IRequest<CreateCategoryCommandResponse>
{
    public CreateCategoryCommandDto? CreateCategoryCommandRequestDto { get; set; }
}
