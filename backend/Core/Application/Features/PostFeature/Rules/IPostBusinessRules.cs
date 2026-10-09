using BlogApp.Core.Application.Common.Models;

namespace BlogApp.Core.Application.Features.PostFeature.Rules;

public interface IPostBusinessRules
{
    Task<Result> CheckPostExistsAsync(Guid postId);
    Task<Result> CheckUserCanEditPostAsync(Guid postId, Guid userId);
    Task<Result> CheckUserCanDeletePostAsync(Guid postId, Guid userId);
    Task<Result> CheckPostIsNotPublishedAsync(Guid postId);
}

