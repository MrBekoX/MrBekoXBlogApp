using System.Security.Claims;
using BlogApp.Presentation.Api.Helpers;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AuthFeature.Commands.LoginCommand;
using BlogApp.Core.Application.Features.AuthFeature.Commands.RefreshTokenCommand;
using BlogApp.Core.Application.Features.AuthFeature.Commands.AdminResetPasswordCommand;
using BlogApp.Core.Application.Features.AuthFeature.Commands.ChangePasswordCommand;
using BlogApp.Core.Application.Features.AuthFeature.Commands.LogoutCommand;
using BlogApp.Core.Application.Features.AuthFeature.Commands.RegisterCommand;
using BlogApp.Core.Application.Features.AuthFeature.DTOs;
using BlogApp.Core.Application.Features.AuthFeature.Queries.GetCurrentUserQuery;
using BlogApp.Presentation.Api.Filters;
using MediatR;

namespace BlogApp.Presentation.Api.Endpoints;

public static class AuthEndpoints
{
    public static IEndpointRouteBuilder RegisterAuthEndpoints(this IEndpointRouteBuilder app)
    {
        var versionedGroup = app.NewVersionedApi("Auth");
        var group = versionedGroup.MapGroup("/api/v{version:apiVersion}/auth")
            .HasApiVersion(1.0)
            .WithTags("Auth");

        // POST /api/v1/auth/login
        group.MapPost("/login", async (
            LoginCommandDto dto,
            IMediator mediator,
            HttpContext context,
            IWebHostEnvironment environment,
            CancellationToken cancellationToken) =>
        {
            var ipAddress = CookieHelper.GetIpAddress(context);
            var response = await mediator.Send(new LoginCommandRequest
            {
                LoginCommandRequestDto = new LoginCommandDto
                {
                    Email = dto.Email,
                    Password = dto.Password,
                    IpAddress = ipAddress
                }
            }, cancellationToken);

            if (!response.IsSuccess)
                return response.ToHttpResult();

            if (response.Value is null)
                return Results.BadRequest(ApiResponse<AuthResponseWithCookiesDto>.FailureResult("Login failed: No response data"));

            var isProduction = !environment.IsDevelopment();
            CookieHelper.SetAuthCookies(
                context.Response,
                response.Value.AccessToken,
                response.Value.RefreshToken,
                response.Value.ExpiresAt,
                isProduction);

            return Results.Ok(ApiResponse<AuthResponseWithCookiesDto>.SuccessResult(new AuthResponseWithCookiesDto
            {
                ExpiresAt = response.Value.ExpiresAt,
                User = response.Value.User
            }, "Login successful"));
        })
        .WithName("Login")
        .WithDescription("User login")
        .Produces<ApiResponse<AuthResponseWithCookiesDto>>(200)
        .Produces(400);

        // POST /api/v1/auth/register
        group.MapPost("/register", async (
            RegisterCommandDto dto,
            IMediator mediator,
            HttpContext context,
            IWebHostEnvironment environment,
            CancellationToken cancellationToken) =>
        {
            var ipAddress = CookieHelper.GetIpAddress(context);
            var response = await mediator.Send(new RegisterCommandRequest
            {
                RegisterCommandRequestDto = new RegisterCommandDto
                {
                    UserName = dto.UserName,
                    Email = dto.Email,
                    Password = dto.Password,
                    ConfirmPassword = dto.ConfirmPassword,
                    FirstName = dto.FirstName,
                    LastName = dto.LastName,
                    IpAddress = ipAddress
                },
                OperationId = context.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            if (!response.IsSuccess)
                return response.ToHttpResult();

            if (response.Value is null)
                return Results.BadRequest(ApiResponse<AuthResponseWithCookiesDto>.FailureResult("Registration failed: No response data"));

            var isProduction = !environment.IsDevelopment();
            CookieHelper.SetAuthCookies(
                context.Response,
                response.Value.AccessToken,
                response.Value.RefreshToken,
                response.Value.ExpiresAt,
                isProduction);

            return Results.Created("/api/v1/auth/login", ApiResponse<AuthResponseWithCookiesDto>.SuccessResult(new AuthResponseWithCookiesDto
            {
                ExpiresAt = response.Value.ExpiresAt,
                User = response.Value.User
            }, "Registration successful"));
        })
        .WithName("Register")
        .WithDescription("User registration")
        .Produces<ApiResponse<AuthResponseWithCookiesDto>>(201)
        .Produces(400);

        // POST /api/v1/auth/refresh-token
        group.MapPost("/refresh-token", async (
            IMediator mediator,
            HttpContext context,
            IWebHostEnvironment environment,
            CancellationToken cancellationToken) =>
        {
            var refreshToken = context.Request.Cookies["refreshToken"];
            var ipAddress = CookieHelper.GetIpAddress(context);
            var isProduction = !environment.IsDevelopment();

            if (string.IsNullOrEmpty(refreshToken))
            {
                CookieHelper.ClearAuthCookies(context.Response, isProduction);
                return Results.BadRequest(ApiResponse<AuthResponseWithCookiesDto>.FailureResult("Refresh token not found"));
            }

            var response = await mediator.Send(new RefreshTokenCommandRequest
            {
                RefreshTokenCommandRequestDto = new RefreshTokenCommandDto
                {
                    RefreshToken = refreshToken,
                    IpAddress = ipAddress
                },
                OperationId = context.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty,
                CustomRequestHash = IdempotencyEndpointHelper.CreateHeaderOnlyRequestHash(
                    "AuthRefreshToken", refreshToken, ipAddress)
            }, cancellationToken);

            if (!response.IsSuccess)
            {
                CookieHelper.ClearAuthCookies(context.Response, isProduction);
                return response.ToHttpResult();
            }

            if (response.Value is null)
            {
                CookieHelper.ClearAuthCookies(context.Response, isProduction);
                return Results.BadRequest(ApiResponse<AuthResponseWithCookiesDto>.FailureResult("Token refresh failed: No response data"));
            }

            CookieHelper.SetAuthCookies(
                context.Response,
                response.Value.AccessToken,
                response.Value.RefreshToken,
                response.Value.ExpiresAt,
                isProduction);

            return Results.Ok(ApiResponse<AuthResponseWithCookiesDto>.SuccessResult(new AuthResponseWithCookiesDto
            {
                ExpiresAt = response.Value.ExpiresAt,
                User = response.Value.User
            }, "Token refreshed"));
        })
        .WithName("RefreshToken")
        .WithDescription("Refresh access token")
        .Produces<ApiResponse<AuthResponseWithCookiesDto>>(200)
        .Produces(400);

        // POST /api/v1/auth/logout
        group.MapPost("/logout", async (
            IMediator mediator,
            HttpContext context,
            IWebHostEnvironment environment,
            CancellationToken cancellationToken) =>
        {
            var refreshToken = context.Request.Cookies["refreshToken"];
            var accessToken = context.Request.Cookies["accessToken"];
            var isProduction = !environment.IsDevelopment();

            await mediator.Send(new LogoutCommandRequest
            {
                RefreshToken = refreshToken,
                AccessToken = accessToken,
                IpAddress = CookieHelper.GetIpAddress(context),
                OperationId = context.Request.Headers["Idempotency-Key"].FirstOrDefault() ?? string.Empty
            }, cancellationToken);

            CookieHelper.ClearAuthCookies(context.Response, isProduction);

            return Results.Ok(ApiResponse<object>.SuccessResult(new { }, "Logged out successfully"));
        })
        .WithName("Logout")
        .WithDescription("Logout and clear auth cookies")
        .Produces<ApiResponse<object>>(200);

        // GET /api/v1/auth/me
        group.MapGet("/me", async (
            IMediator mediator,
            HttpContext context,
            CancellationToken cancellationToken) =>
        {
            var userIdClaim = context.User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (string.IsNullOrEmpty(userIdClaim) || !Guid.TryParse(userIdClaim, out var userId))
                return Results.Json(
                    ApiResponse<UserInfoDto>.FailureResult("User not authenticated or invalid user ID"),
                    statusCode: StatusCodes.Status401Unauthorized);

            var response = await mediator.Send(new GetCurrentUserQueryRequest
            {
                UserId = userId
            }, cancellationToken);

            return response.ToHttpResult();
        })
        .WithName("GetCurrentUser")
        .WithDescription("Get current authenticated user")
        .RequireAuthorization()
        .Produces<ApiResponse<UserInfoDto>>(200)
        .Produces(401);

        // PUT /api/v1/auth/change-password
        group.MapPut("/change-password", async (
            ChangePasswordDto dto,
            IMediator mediator,
            ICurrentUserService currentUserService,
            CancellationToken cancellationToken) =>
        {
            if (currentUserService.UserId is null)
                return Results.Unauthorized();

            var response = await mediator.Send(new ChangePasswordCommandRequest
            {
                Dto = dto,
                UserId = currentUserService.UserId.Value
            }, cancellationToken);

            if (response.IsFailure)
                return response.ToHttpResult();

            return Results.Ok(ApiResponse<object>.SuccessResult(null!, "Password changed successfully."));
        })
        .RequireAuthorization()
        .ValidateAntiforgery()
        .WithName("ChangePassword")
        .WithDescription("Change current user's password")
        .Produces<ApiResponse<object>>(200)
        .Produces(400)
        .Produces(401);

        // PUT /api/v1/auth/admin/reset-password
        group.MapPut("/admin/reset-password", async (
            AdminResetPasswordDto dto,
            IMediator mediator,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new AdminResetPasswordCommandRequest
            {
                Dto = dto
            }, cancellationToken);

            if (response.IsFailure)
                return response.ToHttpResult();

            return Results.Ok(ApiResponse<object>.SuccessResult(null!, "Password reset successfully."));
        })
        .RequireAuthorization(policy => policy.RequireRole("Admin"))
        .ValidateAntiforgery()
        .WithName("AdminResetPassword")
        .WithDescription("Admin: reset any user's password")
        .Produces<ApiResponse<object>>(200)
        .Produces(400)
        .Produces(401)
        .Produces(403);

        return app;
    }
}
