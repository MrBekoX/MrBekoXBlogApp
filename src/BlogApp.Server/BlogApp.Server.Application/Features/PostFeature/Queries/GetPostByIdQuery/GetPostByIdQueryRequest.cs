using MediatR;

namespace BlogApp.Server.Application.Features.PostFeature.Queries.GetPostByIdQuery;

public class GetPostByIdQueryRequest : IRequest<GetPostByIdQueryResponse>
{
    public Guid Id { get; set; }
}
