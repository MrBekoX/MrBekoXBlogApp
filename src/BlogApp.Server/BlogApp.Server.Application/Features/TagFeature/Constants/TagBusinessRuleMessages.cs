namespace BlogApp.Server.Application.Features.TagFeature.Constants;

public static class TagBusinessRuleMessages
{
    // Existence Messages
    public static string TagNotFound(Guid tagId)
        => $"Tag with id '{tagId}' not found";

    public const string TagNotFoundGeneric = "Tag not found";

    // Uniqueness Messages
    public static string TagNameAlreadyExists(string name)
        => $"Tag with name '{name}' already exists";

    // State Messages
    public const string TagAlreadyDeleted = "Tag is already deleted";
}
