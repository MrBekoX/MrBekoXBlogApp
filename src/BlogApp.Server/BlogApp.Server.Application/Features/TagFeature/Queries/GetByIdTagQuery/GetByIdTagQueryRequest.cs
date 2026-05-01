using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.TagFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Application.Features.TagFeature.Queries.GetByIdTagQuery;

public class GetByIdTagQueryRequest : IRequest<Result<GetByIdTagQueryDto>>
{
    public Guid Id { get; set; }
}
