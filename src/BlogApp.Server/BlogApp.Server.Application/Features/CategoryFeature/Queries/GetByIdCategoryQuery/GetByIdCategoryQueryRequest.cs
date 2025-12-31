using MediatR;

namespace BlogApp.Server.Application.Features.CategoryFeature.Queries.GetByIdCategoryQuery;

public class GetByIdCategoryQueryRequest : IRequest<GetByIdCategoryQueryResponse>
{
    public Guid Id { get; set; }
}

