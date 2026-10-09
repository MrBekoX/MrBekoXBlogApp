using BlogApp.Core.Application.Common.BusinessRuleEngine;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.CategoryFeature.Constants;
using BlogApp.Core.Application.Features.CategoryFeature.Rules;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.ValueObjects;
using MediatR;

namespace BlogApp.Core.Application.Features.CategoryFeature.Commands.CreateCategoryCommand;

public class CreateCategoryCommandHandler(
    IUnitOfWork unitOfWork,
    ICategoryBusinessRules categoryBusinessRules,
    ICacheService cacheService) : IRequestHandler<CreateCategoryCommandRequest, Result<Guid>>
{
    public async Task<Result<Guid>> Handle(CreateCategoryCommandRequest request, CancellationToken cancellationToken)
    {
        // Business Rules
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await categoryBusinessRules.CheckCategoryNameIsUniqueAsync(request.CreateCategoryCommandRequestDto!.Name)
        );

        if (!ruleResult.IsSuccess)
        {
            return Result<Guid>.Failure(Error.Conflict(ruleResult.Error ?? string.Empty));
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

        // Invalidate categories cache
        await cacheService.RotateGroupVersionAsync(CategoryCacheKeys.ListGroup, cancellationToken);

        return Result<Guid>.Success(category.Id);
    }
}
