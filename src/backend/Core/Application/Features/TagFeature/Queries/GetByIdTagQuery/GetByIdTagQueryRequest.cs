using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.TagFeature.DTOs;
using MediatR;

namespace BlogApp.Core.Application.Features.TagFeature.Queries.GetByIdTagQuery;

public class GetByIdTagQueryRequest : IRequest<Result<GetByIdTagQueryDto>>
{
    public Guid Id { get; set; }
}
