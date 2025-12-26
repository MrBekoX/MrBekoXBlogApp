using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.DTOs.Categories;
using MediatR;

namespace BlogApp.Server.Application.Features.Categories.Queries;

/// <summary>
/// ID ile kategori getirme sorgusu
/// </summary>
public record GetCategoryByIdQuery(Guid Id) : IRequest<CategoryDetailDto?>;

public class GetCategoryByIdQueryHandler : IRequestHandler<GetCategoryByIdQuery, CategoryDetailDto?>
{
    private readonly IUnitOfWork _unitOfWork;

    public GetCategoryByIdQueryHandler(IUnitOfWork unitOfWork)
    {
        _unitOfWork = unitOfWork;
    }

    public async Task<CategoryDetailDto?> Handle(GetCategoryByIdQuery request, CancellationToken cancellationToken)
    {
        var category = await _unitOfWork.Categories.GetByIdAsync(request.Id, cancellationToken);

        if (category is null || category.IsDeleted)
            return null;

        return new CategoryDetailDto
        {
            Id = category.Id,
            Name = category.Name,
            Slug = category.Slug,
            Description = category.Description,
            ImageUrl = category.ImageUrl,
            DisplayOrder = category.DisplayOrder,
            IsActive = category.IsActive,
            PostCount = 0 // Could be calculated if needed
        };
    }
}

