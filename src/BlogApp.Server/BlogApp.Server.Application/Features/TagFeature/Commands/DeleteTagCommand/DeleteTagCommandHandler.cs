using BlogApp.Server.Application.Common.BusinessRuleEngine;
using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.TagFeature.Constants;
using BlogApp.Server.Application.Features.TagFeature.Rules;
using MediatR;

namespace BlogApp.Server.Application.Features.TagFeature.Commands.DeleteTagCommand;

public class DeleteTagCommandHandler(
    IUnitOfWork unitOfWork,
    ITagBusinessRules tagBusinessRules) : IRequestHandler<DeleteTagCommandRequest, DeleteTagCommandResponse>
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

        var tag = await unitOfWork.Tags.GetByIdAsync(request.Id, cancellationToken);
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

        unitOfWork.Tags.Update(tag);
        await unitOfWork.SaveChangesAsync(cancellationToken);

        return new DeleteTagCommandResponse
        {
            Result = Result.Success()
        };
    }
}
