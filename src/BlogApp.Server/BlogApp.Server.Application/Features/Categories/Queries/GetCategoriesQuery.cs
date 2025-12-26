using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.DTOs.Categories;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.Categories.Queries;

/// <summary>
/// Kategori listesi getirme sorgusu
/// </summary>
public record GetCategoriesQuery : IRequest<List<CategoryDetailDto>>
{
    public bool IncludeInactive { get; init; }
}

public class GetCategoriesQueryHandler : IRequestHandler<GetCategoriesQuery, List<CategoryDetailDto>>
{
    private readonly IUnitOfWork _unitOfWork;

    public GetCategoriesQueryHandler(IUnitOfWork unitOfWork)
    {
        _unitOfWork = unitOfWork;
    }

    public async Task<List<CategoryDetailDto>> Handle(GetCategoriesQuery request, CancellationToken cancellationToken)
    {
        var query = _unitOfWork.Categories.Query()
            .AsNoTracking()
            .Include(c => c.Posts)
            .Where(c => !c.IsDeleted);

        if (!request.IncludeInactive)
        {
            query = query.Where(c => c.IsActive);
        }

        return await query
            .OrderBy(c => c.DisplayOrder)
            .ThenBy(c => c.Name)
            .Select(c => new CategoryDetailDto
            {
                Id = c.Id,
                Name = c.Name,
                Slug = c.Slug,
                Description = c.Description,
                ImageUrl = c.ImageUrl,
                DisplayOrder = c.DisplayOrder,
                IsActive = c.IsActive,
                PostCount = c.Posts.Count(p => !p.IsDeleted),
                CreatedAt = c.CreatedAt
            })
            .ToListAsync(cancellationToken);
    }
}
