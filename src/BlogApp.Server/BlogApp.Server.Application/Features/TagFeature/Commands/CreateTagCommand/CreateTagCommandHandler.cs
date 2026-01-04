using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.TagFeature.Constants;
using BlogApp.Server.Application.Features.TagFeature.Rules;
using BlogApp.Server.Domain.Entities;
using BlogApp.Server.Domain.ValueObjects;
using MediatR;

namespace BlogApp.Server.Application.Features.TagFeature.Commands.CreateTagCommand;

public class CreateTagCommandHandler(
    IUnitOfWork unitOfWork,
    ITagBusinessRules tagBusinessRules,
    ICacheService cacheService) : IRequestHandler<CreateTagCommandRequest, CreateTagCommandResponse>
{
    public async Task<CreateTagCommandResponse> Handle(CreateTagCommandRequest request, CancellationToken cancellationToken)
    {
        // Business Rules
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await tagBusinessRules.CheckTagNameIsUniqueAsync(request.CreateTagCommandRequestDto!.Name)
        );

        if (!ruleResult.IsSuccess)
        {
            return new CreateTagCommandResponse
            {
                Result = Result<Guid>.Failure(ruleResult.Error!)
            };
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

        return new CreateTagCommandResponse
        {
            Result = Result<Guid>.Success(tag.Id)
        };
    }
}



