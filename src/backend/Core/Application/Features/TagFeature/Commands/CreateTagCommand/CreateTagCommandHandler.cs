using BlogApp.Core.Application.Common.BusinessRuleEngine;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Persistence;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.TagFeature.Constants;
using BlogApp.Core.Application.Features.TagFeature.Rules;
using BlogApp.Core.Domain.Entities;
using BlogApp.Core.Domain.ValueObjects;
using MediatR;

namespace BlogApp.Core.Application.Features.TagFeature.Commands.CreateTagCommand;

public class CreateTagCommandHandler(
    IUnitOfWork unitOfWork,
    ITagBusinessRules tagBusinessRules,
    ICacheService cacheService) : IRequestHandler<CreateTagCommandRequest, Result<Guid>>
{
    public async Task<Result<Guid>> Handle(CreateTagCommandRequest request, CancellationToken cancellationToken)
    {
        // Business Rules
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await tagBusinessRules.CheckTagNameIsUniqueAsync(request.CreateTagCommandRequestDto!.Name)
        );

        if (!ruleResult.IsSuccess)
        {
            return Result<Guid>.Failure(Error.Conflict(ruleResult.Error ?? string.Empty));
        }

        var slug = Slug.CreateFromTitle(request.CreateTagCommandRequestDto!.Name);

        var tag = new Tag
        {
            Id = Guid.NewGuid(),
            Name = request.CreateTagCommandRequestDto.Name,
            Slug = slug.Value,
            CreatedAt = DateTime.UtcNow
        };

        await unitOfWork.TagsWrite.AddAsync(tag, cancellationToken);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        // Invalidate tags cache
        await cacheService.RotateGroupVersionAsync(TagCacheKeys.ListGroup, cancellationToken);

        return Result<Guid>.Success(tag.Id);
    }
}
