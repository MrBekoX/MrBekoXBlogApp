using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.CategoryFeature.Rules;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.ValueObjects;
using MediatR;

namespace BlogApp.Server.Application.Features.CategoryFeature.Commands.CreateCategoryCommand;

public class CreateCategoryCommandHandler(
    IUnitOfWork unitOfWork,
    ICategoryBusinessRules categoryBusinessRules) : IRequestHandler<CreateCategoryCommandRequest, CreateCategoryCommandResponse>
{
    public async Task<CreateCategoryCommandResponse> Handle(CreateCategoryCommandRequest request, CancellationToken cancellationToken)
    {
        // Business Rules
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await categoryBusinessRules.CheckCategoryNameIsUniqueAsync(request.CreateCategoryCommandRequestDto!.Name)
        );

        if (!ruleResult.IsSuccess)
        {
            return new CreateCategoryCommandResponse
            {
                Result = Result<Guid>.Failure(ruleResult.Error!)
            };
        }

        var slug = Slug.CreateFromTitle(request.CreateCategoryCommandRequestDto!.Name);

        var category = new Category
        {
            Id = Guid.NewGuid(),
            Name = request.CreateCategoryCommandRequestDto.Name,
            Slug = slug.Value,
            Description = request.CreateCategoryCommandRequestDto.Description,
            ImageUrl = request.CreateCategoryCommandRequestDto.ImageUrl,
            DisplayOrder = request.CreateCategoryCommandRequestDto.DisplayOrder,
            IsActive = true,
            CreatedAt = DateTime.UtcNow
        };

        await unitOfWork.CategoriesWrite.AddAsync(category, cancellationToken);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        return new CreateCategoryCommandResponse
        {
            Result = Result<Guid>.Success(category.Id)
        };
    }
}



