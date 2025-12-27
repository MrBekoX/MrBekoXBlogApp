namespace BlogApp.Server.Application.Features.AuthFeature.Constants;

public static class AuthValidationMessages
{
    public const string EmailRequired = "Email is required";
    public const string EmailInvalid = "Email is not valid";
    public const string PasswordRequired = "Password is required";
    public const string PasswordMinLength = "Password must be at least 6 characters";
    public const string PasswordMaxLength = "Password must not exceed 100 characters";
    public const string UserNameRequired = "Username is required";
    public const string UserNameMinLength = "Username must be at least 3 characters";
    public const string UserNameMaxLength = "Username must not exceed 50 characters";
    public const string ConfirmPasswordRequired = "Confirm password is required";
    public const string PasswordsDoNotMatch = "Passwords do not match";
    public const string RefreshTokenRequired = "Refresh token is required";
}
