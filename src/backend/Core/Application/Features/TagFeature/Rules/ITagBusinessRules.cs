using BlogApp.Core.Application.Common.Models;

namespace BlogApp.Core.Application.Features.TagFeature.Rules;

public interface ITagBusinessRules
{
    // ============== EXISTENCE & UNIQUENESS ==============
    Task<Result> CheckTagExistsAsync(Guid tagId);
    Task<Result> CheckTagNameIsUniqueAsync(string name);
}

