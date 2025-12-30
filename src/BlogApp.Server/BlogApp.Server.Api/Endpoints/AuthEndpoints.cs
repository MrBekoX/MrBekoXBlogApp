using System.Security.Claims;
using BlogApp.Server.Api.Helpers;
using BlogApp.Server.Application.Common.Interfaces;
using BlogApp.Server.Application.Common.Models;
using BlogApp.Server.Application.Features.AuthFeature.Commands.LoginCommand;
using BlogApp.Server.Application.Features.AuthFeature.Commands.RefreshTokenCommand;
using BlogApp.Server.Application.Features.AuthFeature.Commands.RegisterCommand;
using BlogApp.Server.Application.Features.AuthFeature.DTOs;
using MediatR;

namespace BlogApp.Server.Api.Endpoints;

public static class AuthEndpoints
{
    public static IEndpointRouteBuilder RegisterAuthEndpoints(this IEndpointRouteBuilder app)
    {
        var versionedGroup = app.NewVersionedApi("Auth");
        var group = versionedGroup.MapGroup("/api/v{version:apiVersion}/auth")
            .HasApiVersion(1.0)
            .WithTags("Auth");

        // POST /api/auth/login
        group.MapPost("/login", async (
            LoginCommandDto dto,
            IMediator mediator,
            HttpContext context,
            IWebHostEnvironment environment,
            CancellationToken cancellationToken) =>
        {
            var response = await mediator.Send(new LoginCommandRequest
            {
                LoginCommandRequestDto = new LoginCommandDto
                {
                    Email = dto.Email,
                    Password = dto.Password,
                    IpAddress = CookieHelper.GetIpAddress(context)
                }
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.BadRequest(ApiResponse<AuthResponseWithCookiesDto>.FailureResult(response.Result.Error!));

            var isProduction = !environment.IsDevelopment();
            CookieHelper.SetAuthCookies(
                context.Response,
                response.Result.Value!.AccessToken,
                response.Result.Value.RefreshToken,
                response.Result.Value.ExpiresAt,
                isProduction);

            var result = new AuthResponseWithCookiesDto
            {
                ExpiresAt = response.Result.Value.ExpiresAt,
                User = response.Result.Value.User
            };

            return Results.Ok(ApiResponse<AuthResponseWithCookiesDto>.SuccessResult(result, "Login successful"));
        })
        .WithName("Login")
        .WithDescription("User login")
        .Produces<ApiResponse<AuthResponseWithCookiesDto>>(200)
        .Produces(400);

        // POST /api/auth/register
        group.MapPost("/register", async (
            RegisterCommandDto dto,
            IMediator mediator,
            HttpContext context,
            IWebHostEnvironment environment,
            CancellationToken cancellationToken) =>
        {
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
                    IpAddress = CookieHelper.GetIpAddress(context)
                }
            }, cancellationToken);

            if (!response.Result.IsSuccess)
                return Results.BadRequest(ApiResponse<AuthResponseWithCookiesDto>.FailureResult(response.Result.Error!));

            var isProduction = !environment.IsDevelopment();
            CookieHelper.SetAuthCookies(
                context.Response,
                response.Result.Value!.AccessToken,
                response.Result.Value.RefreshToken,
                response.Result.Value.ExpiresAt,
                isProduction);

            var result = new AuthResponseWithCookiesDto
            {
                ExpiresAt = response.Result.Value.ExpiresAt,
                User = response.Result.Value.User
            };

            return Results.Created("/api/auth/login", ApiResponse<AuthResponseWithCookiesDto>.SuccessResult(result, "Registration successful"));
        })
        .WithName("Register")
        .WithDescription("User registration")
        .Produces<ApiResponse<AuthResponseWithCookiesDto>>(201)
        .Produces(400);

        // POST /api/auth/refresh-token
        group.MapPost("/refresh-token", async (
            IMediator mediator,
            HttpContext context,
            IWebHostEnvironment environment,
            CancellationToken cancellationToken) =>
        {
            var refreshToken = context.Request.Cookies["BlogApp.RefreshToken"];
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
                    IpAddress = CookieHelper.GetIpAddress(context)
                }
            }, cancellationToken);

            if (!response.Result.IsSuccess)
            {
                CookieHelper.ClearAuthCookies(context.Response, isProduction);
                return Results.BadRequest(ApiResponse<AuthResponseWithCookiesDto>.FailureResult(response.Result.Error!));
            }

            CookieHelper.SetAuthCookies(
                context.Response,
                response.Result.Value!.AccessToken,
                response.Result.Value.RefreshToken,
                response.Result.Value.ExpiresAt,
                isProduction);

            var result = new AuthResponseWithCookiesDto
            {
                ExpiresAt = response.Result.Value.ExpiresAt,
                User = response.Result.Value.User
            };

            return Results.Ok(ApiResponse<AuthResponseWithCookiesDto>.SuccessResult(result, "Token refreshed"));
        })
        .WithName("RefreshToken")
        .WithDescription("Refresh access token")
        .Produces<ApiResponse<AuthResponseWithCookiesDto>>(200)
        .Produces(400);

        // POST /api/auth/logout
        group.MapPost("/logout", async (
            IUnitOfWork unitOfWork,
            HttpContext context,
            IWebHostEnvironment environment,
            CancellationToken cancellationToken) =>
        {
            var refreshToken = context.Request.Cookies["BlogApp.RefreshToken"];
            var isProduction = !environment.IsDevelopment();

            if (!string.IsNullOrEmpty(refreshToken))
            {
                var storedToken = await unitOfWork.RefreshTokensRead.GetSingleAsync(t => t.Token == refreshToken);

                if (storedToken != null)
                {
                    storedToken.RevokedAt = DateTime.UtcNow;
                    storedToken.RevokedByIp = CookieHelper.GetIpAddress(context);
                    storedToken.ReasonRevoked = "Logged out";
                    await unitOfWork.RefreshTokensWrite.UpdateAsync(storedToken);
                    await unitOfWork.SaveChangesAsync(cancellationToken);
                }
            }

            CookieHelper.ClearAuthCookies(context.Response, isProduction);

            return Results.Ok(ApiResponse<object>.SuccessResult(new { }, "Logged out successfully"));
        })
        .WithName("Logout")
        .WithDescription("Logout and clear auth cookies")
        .Produces<ApiResponse<object>>(200);

        // GET /api/auth/me
        group.MapGet("/me", async (
            IUnitOfWork unitOfWork,
            HttpContext context,
            CancellationToken cancellationToken) =>
        {
            var userIdClaim = context.User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (string.IsNullOrEmpty(userIdClaim) || !Guid.TryParse(userIdClaim, out var userId))
                return Results.Unauthorized();

            var user = await unitOfWork.UsersRead.GetByIdAsync(userId);
            if (user is null)
                return Results.NotFound(ApiResponse<UserInfoDto>.FailureResult("User not found"));

            var userInfo = new UserInfoDto
            {
                Id = user.Id,
                UserName = user.UserName,
                Email = user.Email,
                FullName = user.FullName,
                AvatarUrl = user.AvatarUrl,
                Role = user.Role.ToString()
            };

            return Results.Ok(ApiResponse<UserInfoDto>.SuccessResult(userInfo));
        })
        .WithName("GetCurrentUser")
        .WithDescription("Get current authenticated user")
        .RequireAuthorization()
        .Produces<ApiResponse<UserInfoDto>>(200)
        .Produces(401);

        return app;
    }
}
