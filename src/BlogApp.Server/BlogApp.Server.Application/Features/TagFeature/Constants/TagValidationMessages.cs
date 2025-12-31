namespace BlogApp.Server.Application.Features.TagFeature.Constants;

public static class TagValidationMessages
{
    // Name Validation Messages
    public const string NameRequired = "Tag name is required";
    public const string NameRequiredCode = "TAG_NAME_REQUIRED";

    public const string NameTooShort = "Tag name must be at least {MinLength} characters long";
    public const string NameTooShortCode = "TAG_NAME_TOO_SHORT";

    public const string NameTooLong = "Tag name cannot exceed {MaxLength} characters";
    public const string NameTooLongCode = "TAG_NAME_TOO_LONG";

    // Id Validation Messages
    public const string IdRequired = "Tag id is required";
    public const string IdRequiredCode = "TAG_ID_REQUIRED";

    public const string IdInvalid = "Tag id is invalid";
    public const string IdInvalidCode = "TAG_ID_INVALID";

    // Validation Constraints
    public const int NameMinLength = 2;
    public const int NameMaxLength = 50;
}

