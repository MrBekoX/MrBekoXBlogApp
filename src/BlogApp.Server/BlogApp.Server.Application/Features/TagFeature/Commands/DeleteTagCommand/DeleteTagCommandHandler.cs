using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.TagFeature.Constants;
using BlogApp.Server.Application.Features.TagFeature.Rules;
using MediatR;

namespace BlogApp.Server.Application.Features.TagFeature.Commands.DeleteTagCommand;

public class DeleteTagCommandHandler(
    IUnitOfWork unitOfWork,
    ITagBusinessRules tagBusinessRules,
    ICacheService cacheService) : IRequestHandler<DeleteTagCommandRequest, DeleteTagCommandResponse>
{
    public async Task<DeleteTagCommandResponse> Handle(DeleteTagCommandRequest request, CancellationToken cancellationToken)
    {
        // Business Rules
        var ruleResult = await BusinessRuleEngine.RunAsync(
            async () => await tagBusinessRules.CheckTagExistsAsync(request.Id)
        );

        if (!ruleResult.IsSuccess)
        {
            return new DeleteTagCommandResponse
            {
                Result = Result.Failure(ruleResult.Error!)
            };
        }

        var tag = await unitOfWork.TagsRead.GetSingleAsync(t => t.Id == request.Id && !t.IsDeleted, cancellationToken);
        if (tag is null)
        {
            return new DeleteTagCommandResponse
            {
                Result = Result.Failure(TagBusinessRuleMessages.TagNotFoundGeneric)
            };
        }

        // Soft delete
        tag.IsDeleted = true;
        tag.UpdatedAt = DateTime.UtcNow;

        await unitOfWork.TagsWrite.UpdateAsync(tag, cancellationToken);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        // Invalidate tags cache
        await cacheService.RotateGroupVersionAsync(TagCacheKeys.ListGroup, cancellationToken);

        return new DeleteTagCommandResponse
        {
            Result = Result.Success()
        };
    }
}



