using MediatR;

namespace BlogApp.Server.Application.Features.AuthFeature.Queries.GetCurrentUserQuery;

public class GetCurrentUserQueryRequest : IRequest<GetCurrentUserQueryResponse>
{
    public Guid UserId { get; set; }
}
