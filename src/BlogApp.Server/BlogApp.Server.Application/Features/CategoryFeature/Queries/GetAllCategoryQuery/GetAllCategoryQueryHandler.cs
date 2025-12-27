using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.CategoryFeature.DTOs;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Server.Application.Features.CategoryFeature.Queries.GetAllCategoryQuery;

public class GetAllCategoryQueryHandler(
    IUnitOfWork unitOfWork) : IRequestHandler<GetAllCategoryQueryRequest, GetAllCategoryQueryResponse>
{
    public async Task<GetAllCategoryQueryResponse> Handle(GetAllCategoryQueryRequest request, CancellationToken cancellationToken)
    {
        var query = unitOfWork.Categories.Query()
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
                PostCount = c.Posts.Count(p => !p.IsDeleted),
                CreatedAt = c.CreatedAt
            })
            .ToListAsync(cancellationToken);

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
