using MediatR;

namespace BlogApp.Server.Application.Features.CategoryFeature.Queries.GetAllCategoryQuery;

public class GetAllCategoryQueryRequest : IRequest<GetAllCategoryQueryResponse>
{
    public bool IncludeInactive { get; set; }
    
    /// <summary>
    /// true ise, yayınlanmış yazısı olmayan kategoriler sonuçlardan çıkarılır
    /// </summary>
    public bool ExcludeEmptyCategories { get; set; }
}

