using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.CategoryFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.CategoryFeature.Queries.GetAllCategoryQuery;

public class GetAllCategoryQueryRequest : IRequest<Result<IReadOnlyList<GetAllCategoryQueryDto>>>
{
    public bool IncludeInactive { get; set; }

    /// <summary>
    /// true ise, yayınlanmış yazısı olmayan kategoriler sonuçlardan çıkarılır
    /// </summary>
    public bool ExcludeEmptyCategories { get; set; }
}
