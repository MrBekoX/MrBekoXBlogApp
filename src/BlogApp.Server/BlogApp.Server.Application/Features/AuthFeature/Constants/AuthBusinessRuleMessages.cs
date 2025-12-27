namespace BlogApp.Server.Application.Features.AuthFeature.Constants;

public static class AuthBusinessRuleMessages
{
    public const string InvalidCredentials = "Invalid email or password";
    public const string AccountLocked = "Account is locked. Try again later.";
    public const string AccountDisabled = "Account is disabled";
    public const string EmailAlreadyExists = "Email is already in use";
    public const string UserNameAlreadyExists = "Username is already taken";
    public const string InvalidRefreshToken = "Invalid refresh token";
    public const string RefreshTokenExpired = "Refresh token is expired or revoked";
    public const string UserNotFound = "User not found or inactive";

    public static string AccountLockedWithTime(int minutes) => $"Account is locked. Try again in {minutes} minutes.";
    public static string RemainingAttempts(int attempts) => $"Invalid email or password. {attempts} attempts remaining.";
    public static string TooManyAttempts(int minutes) => $"Too many failed attempts. Account locked for {minutes} minutes.";
}
