namespace BlogApp.Server.Application.Features.PostFeature.Constants;

public static class PostValidationMessages
{
    public const string TitleRequired = "Title is required";
    public const string TitleMinLength = "Title must be at least 3 characters";
    public const string TitleMaxLength = "Title must not exceed 200 characters";
    public const string ContentRequired = "Content is required";
    public const string ContentMinLength = "Content must be at least 10 characters";
    public const string ContentMaxLength = "Content must not exceed 500,000 characters";
    public const string TagNameMaxLength = "Tag name must not exceed 50 characters";
    public const string TagNameInvalid = "Tag name contains invalid characters";
    public const string FeaturedImageUrlInvalid = "Featured image URL is not valid or points to a restricted address";
    public const string ExcerptMaxLength = "Excerpt must not exceed 500 characters";
    public const string MetaTitleMaxLength = "Meta title must not exceed 70 characters";
    public const string MetaDescriptionMaxLength = "Meta description must not exceed 160 characters";
    public const string MetaKeywordsMaxLength = "Meta keywords must not exceed 200 characters";
    public const string IdRequired = "Post ID is required";
    public const string SlugRequired = "Slug is required";
    public const string FeaturedImageUrlMaxLength = "Featured image URL must not exceed 500 characters";
    public const string DraftDataRequired = "Draft data is required";
}

