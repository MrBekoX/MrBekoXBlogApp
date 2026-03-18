namespace BlogApp.Server.Application.Features.PostFeature.Constants;

public static class PostBusinessRuleMessages
{
    public const string PostNotFoundGeneric = "Post not found";
    public const string UserNotAuthenticated = "User not authenticated";
    public const string UnauthorizedToEditPost = "You are not authorized to edit this post";
    public const string UnauthorizedToDeletePost = "You are not authorized to delete this post";
    public const string PostAlreadyPublished = "Post is already published";
    public const string PostNotPublished = "Post is not published";
    public const string CannotDeletePublishedPost = "Cannot delete a published post. Unpublish it first.";
    public const string PostModifiedConcurrently = "The post was modified by another request. Reload and retry.";

    public static string PostNotFound(Guid postId) => $"Post with ID '{postId}' was not found";
    public static string PostNotFoundBySlug(string slug) => $"Post with slug '{slug}' was not found";
}

