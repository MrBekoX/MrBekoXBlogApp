namespace BlogApp.Server.Application.Features.PostFeature.Constants;

public static class PostValidationMessages
{
    public const string TitleRequired = "Title is required";
    public const string TitleMinLength = "Title must be at least 3 characters";
    public const string TitleMaxLength = "Title must not exceed 200 characters";
    public const string ContentRequired = "Content is required";
    public const string ContentMinLength = "Content must be at least 10 characters";
    public const string ExcerptMaxLength = "Excerpt must not exceed 500 characters";
    public const string MetaTitleMaxLength = "Meta title must not exceed 70 characters";
    public const string MetaDescriptionMaxLength = "Meta description must not exceed 160 characters";
    public const string MetaKeywordsMaxLength = "Meta keywords must not exceed 200 characters";
    public const string IdRequired = "Post ID is required";
    public const string SlugRequired = "Slug is required";
    public const string FeaturedImageUrlMaxLength = "Featured image URL must not exceed 500 characters";
}
