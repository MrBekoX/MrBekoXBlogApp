using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.CategoryFeature.DTOs;
using BlogApp.Server.Domain.Enums;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.CategoryFeature.Queries.GetAllCategoryQuery;

public class GetAllCategoryQueryHandler(
    IUnitOfWork unitOfWork) : IRequestHandler<GetAllCategoryQueryRequest, GetAllCategoryQueryResponse>
{
    public async Task<GetAllCategoryQueryResponse> Handle(GetAllCategoryQueryRequest request, CancellationToken cancellationToken)
    {
        var query = unitOfWork.CategoriesRead.GetAll()
            .AsNoTracking()
            .Include(c => c.Posts)
            .Where(c => !c.IsDeleted);

        if (!request.IncludeInactive)
        {
            query = query.Where(c => c.IsActive);
        }

        var categories = await query
            .OrderBy(c => c.DisplayOrder)
            .ThenBy(c => c.Name)
            .Select(c => new GetAllCategoryQueryDto
            {
                Id = c.Id,
                Name = c.Name,
                Slug = c.Slug,
                Description = c.Description,
                ImageUrl = c.ImageUrl,
                DisplayOrder = c.DisplayOrder,
                IsActive = c.IsActive,
                // Yalnızca yayınlanmış ve silinmemiş postları say
                PostCount = c.Posts.Count(p => !p.IsDeleted && p.Status == PostStatus.Published),
                CreatedAt = c.CreatedAt
            })
            .ToListAsync(cancellationToken);

        // Boş kategorileri filtrele (istenirse)
        if (request.ExcludeEmptyCategories)
        {
            categories = categories.Where(c => c.PostCount > 0).ToList();
        }

        if (!categories.Any())
        {
            return new GetAllCategoryQueryResponse
            {
                Result = Result<IEnumerable<GetAllCategoryQueryDto>>.Success(Enumerable.Empty<GetAllCategoryQueryDto>())
            };
        }

        return new GetAllCategoryQueryResponse
        {
            Result = Result<IEnumerable<GetAllCategoryQueryDto>>.Success(categories)
        };
    }
}



