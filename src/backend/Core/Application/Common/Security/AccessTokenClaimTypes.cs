namespace BlogApp.Core.Application.Common.Security;

public static class AccessTokenClaimTypes
{
    // Our iat uses whole seconds; the signed companion preserves the
    // order of password changes and fresh logins occurring within one second.
    public const string IssuedAtTicks = "issued_at_ticks";
}
