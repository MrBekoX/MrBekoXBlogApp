namespace BlogApp.Server.Application.Features.AuthFeature.Constants;

public static class AuthValidationMessages
{
    // Email
    public const string EmailRequired = "Email is required";
    public const string EmailInvalid = "Email is not valid";

    // Password
    public const string PasswordRequired = "Password is required";
    public const string PasswordMinLength = "Password must be at least 8 characters";
    public const string PasswordMaxLength = "Password must not exceed 100 characters";
    public const string PasswordRequiresUppercase = "Password must contain at least one uppercase letter";
    public const string PasswordRequiresLowercase = "Password must contain at least one lowercase letter";
    public const string PasswordRequiresDigit = "Password must contain at least one number";
    public const string PasswordRequiresSpecialChar = "Password must contain at least one special character (!@#$%^&* etc.)";
    public const string ConfirmPasswordRequired = "Confirm password is required";
    public const string PasswordsDoNotMatch = "Passwords do not match";

    // Username
    public const string UserNameRequired = "Username is required";
    public const string UserNameMinLength = "Username must be at least 3 characters";
    public const string UserNameMaxLength = "Username must not exceed 50 characters";

    // Token
    public const string RefreshTokenRequired = "Refresh token is required";
}

