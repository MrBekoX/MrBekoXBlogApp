using MediatR;

namespace BlogApp.Server.Application.Features.TagFeature.Queries.GetByIdTagQuery;

public class GetByIdTagQueryRequest : IRequest<GetByIdTagQueryResponse>
{
    public Guid Id { get; set; }
}
