namespace BlogApp.Server.Application.Features.CategoryFeature.Constants;

public static class CategoryValidationMessages
{
    // Name Validation Messages
    public const string NameRequired = "Category name is required";
    public const string NameRequiredCode = "CATEGORY_NAME_REQUIRED";

    public const string NameTooShort = "Category name must be at least {MinLength} characters long";
    public const string NameTooShortCode = "CATEGORY_NAME_TOO_SHORT";

    public const string NameTooLong = "Category name cannot exceed {MaxLength} characters";
    public const string NameTooLongCode = "CATEGORY_NAME_TOO_LONG";

    // Description Validation Messages
    public const string DescriptionTooLong = "Description cannot exceed {MaxLength} characters";
    public const string DescriptionTooLongCode = "CATEGORY_DESCRIPTION_TOO_LONG";

    // Id Validation Messages
    public const string IdRequired = "Category id is required";
    public const string IdRequiredCode = "CATEGORY_ID_REQUIRED";

    public const string IdInvalid = "Category id is invalid";
    public const string IdInvalidCode = "CATEGORY_ID_INVALID";

    // Validation Constraints
    public const int NameMinLength = 2;
    public const int NameMaxLength = 100;
    public const int DescriptionMaxLength = 500;
}

