using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Features.TagFeature.Rules;

public interface ITagBusinessRules
{
    // ============== EXISTENCE & UNIQUENESS ==============
    Task<Result> CheckTagExistsAsync(Guid tagId);
    Task<Result> CheckTagNameIsUniqueAsync(string name);
}

