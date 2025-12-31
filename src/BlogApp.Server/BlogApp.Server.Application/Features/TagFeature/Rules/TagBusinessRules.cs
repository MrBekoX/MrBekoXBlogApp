using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.TagFeature.Constants;
using BlogApp.Server.Domain.ValueObjects;

namespace BlogApp.Server.Application.Features.TagFeature.Rules;

public class TagBusinessRules : ITagBusinessRules
{
    private readonly IUnitOfWork _unitOfWork;

    public TagBusinessRules(IUnitOfWork unitOfWork)
    {
        _unitOfWork = unitOfWork;
    }

    // ============== EXISTENCE & UNIQUENESS ==============

    public async Task<Result> CheckTagExistsAsync(Guid tagId)
    {
        var tag = await _unitOfWork.TagsRead.GetByIdAsync(tagId);

        return tag is not null && !tag.IsDeleted
            ? Result.Success()
            : Result.Failure(TagBusinessRuleMessages.TagNotFound(tagId));
    }

    public async Task<Result> CheckTagNameIsUniqueAsync(string name)
    {
        var slug = Slug.CreateFromTitle(name);
        var existingTag = await _unitOfWork.TagsRead.GetSingleAsync(
            t => t.Slug == slug.Value && !t.IsDeleted);

        return existingTag is null
            ? Result.Success()
            : Result.Failure(TagBusinessRuleMessages.TagNameAlreadyExists(name));
    }
}

