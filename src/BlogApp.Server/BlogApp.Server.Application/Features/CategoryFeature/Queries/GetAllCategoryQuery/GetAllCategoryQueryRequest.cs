using MediatR;

namespace BlogApp.Server.Application.Features.CategoryFeature.Queries.GetAllCategoryQuery;

public class GetAllCategoryQueryRequest : IRequest<GetAllCategoryQueryResponse>
{
    public bool IncludeInactive { get; set; }
}

