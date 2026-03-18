using System.Security.Claims;
using BlogApp.Server.Api.Helpers;
using BlogApp.Server.Application.Common.Interfaces.Data;
using BlogApp.Server.Application.Common.Interfaces.Persistence;
using BlogApp.Server.Application.Common.Interfaces.Services;
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

        // POST /api/v1/auth/login
        group.MapPost("/login", async (
            LoginCommandDto dto,
            IMediator mediator,
            HttpContext context,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            IWebHostEnvironment environment,
            CancellationToken cancellationToken) =>
        {
            var ipAddress = CookieHelper.GetIpAddress(context);
            var requestPayload = new
            {
                dto.Email,
                dto.Password,
                IpAddress = ipAddress
            };

            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                context,
                "AuthLogin",
                requestPayload,
                unitOfWork,
                idempotencyService,
                currentUserService,
                cancellationToken,
                requireIdempotencyKey: true);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            try
            {
                var response = await mediator.Send(new LoginCommandRequest
                {
                    LoginCommandRequestDto = new LoginCommandDto
                    {
                        Email = dto.Email,
                        Password = dto.Password,
                        IpAddress = ipAddress
                    }
                }, cancellationToken);

                if (!response.Result.IsSuccess)
                {
                    var badRequest = ApiResponse<AuthResponseWithCookiesDto>.FailureResult(response.Result.Error!);
                    await scope.CompleteAndCommitAsync(
                        StatusCodes.Status400BadRequest,
                        badRequest,
                        idempotencyService,
                        cancellationToken,
                        context.Response);
                    return Results.BadRequest(badRequest);
                }

                if (response.Result.Value is null)
                {
                    var badRequest = ApiResponse<AuthResponseWithCookiesDto>.FailureResult("Login failed: No response data");
                    await scope.CompleteAndCommitAsync(
                        StatusCodes.Status400BadRequest,
                        badRequest,
                        idempotencyService,
                        cancellationToken,
                        context.Response);
                    return Results.BadRequest(badRequest);
                }

                var isProduction = !environment.IsDevelopment();
                CookieHelper.SetAuthCookies(
                    context.Response,
                    response.Result.Value.AccessToken,
                    response.Result.Value.RefreshToken,
                    response.Result.Value.ExpiresAt,
                    isProduction);

                var result = ApiResponse<AuthResponseWithCookiesDto>.SuccessResult(new AuthResponseWithCookiesDto
                {
                    ExpiresAt = response.Result.Value.ExpiresAt,
                    User = response.Result.Value.User
                }, "Login successful");

                await scope.CompleteAndCommitAsync(
                    StatusCodes.Status200OK,
                    result,
                    idempotencyService,
                    cancellationToken,
                    context.Response);

                return Results.Ok(result);
            }
            catch
            {
                throw;
            }
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
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            IWebHostEnvironment environment,
            CancellationToken cancellationToken) =>
        {
            var ipAddress = CookieHelper.GetIpAddress(context);
            var requestPayload = new
            {
                dto.UserName,
                dto.Email,
                dto.Password,
                dto.ConfirmPassword,
                dto.FirstName,
                dto.LastName,
                IpAddress = ipAddress
            };

            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                context,
                "AuthRegister",
                requestPayload,
                unitOfWork,
                idempotencyService,
                currentUserService,
                cancellationToken,
                requireIdempotencyKey: true);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            try
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
                        IpAddress = ipAddress
                    }
                }, cancellationToken);

                if (!response.Result.IsSuccess)
                {
                    var badRequest = ApiResponse<AuthResponseWithCookiesDto>.FailureResult(response.Result.Error!);
                    await scope.CompleteAndCommitAsync(
                        StatusCodes.Status400BadRequest,
                        badRequest,
                        idempotencyService,
                        cancellationToken,
                        context.Response);
                    return Results.BadRequest(badRequest);
                }

                if (response.Result.Value is null)
                {
                    var badRequest = ApiResponse<AuthResponseWithCookiesDto>.FailureResult("Registration failed: No response data");
                    await scope.CompleteAndCommitAsync(
                        StatusCodes.Status400BadRequest,
                        badRequest,
                        idempotencyService,
                        cancellationToken,
                        context.Response);
                    return Results.BadRequest(badRequest);
                }

                var isProduction = !environment.IsDevelopment();
                CookieHelper.SetAuthCookies(
                    context.Response,
                    response.Result.Value.AccessToken,
                    response.Result.Value.RefreshToken,
                    response.Result.Value.ExpiresAt,
                    isProduction);

                context.Response.Headers.Location = "/api/v1/auth/login";
                var result = ApiResponse<AuthResponseWithCookiesDto>.SuccessResult(new AuthResponseWithCookiesDto
                {
                    ExpiresAt = response.Result.Value.ExpiresAt,
                    User = response.Result.Value.User
                }, "Registration successful");

                await scope.CompleteAndCommitAsync(
                    StatusCodes.Status201Created,
                    result,
                    idempotencyService,
                    cancellationToken,
                    context.Response);

                return Results.Created("/api/v1/auth/login", result);
            }
            catch
            {
                throw;
            }
        })
        .WithName("Register")
        .WithDescription("User registration")
        .Produces<ApiResponse<AuthResponseWithCookiesDto>>(201)
        .Produces(400);

        // POST /api/v1/auth/refresh-token
        group.MapPost("/refresh-token", async (
            IMediator mediator,
            HttpContext context,
            IUnitOfWork unitOfWork,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            IWebHostEnvironment environment,
            CancellationToken cancellationToken) =>
        {
            var refreshToken = context.Request.Cookies["refreshToken"];
            var ipAddress = CookieHelper.GetIpAddress(context);
            var isProduction = !environment.IsDevelopment();
            var requestHash = IdempotencyEndpointHelper.CreateHeaderOnlyRequestHash(
                "AuthRefreshToken",
                refreshToken,
                ipAddress);

            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                context,
                "AuthRefreshToken",
                new
                {
                    HasRefreshToken = !string.IsNullOrWhiteSpace(refreshToken)
                },
                unitOfWork,
                idempotencyService,
                currentUserService,
                cancellationToken,
                requireIdempotencyKey: true,
                requestHash: requestHash);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            try
            {
                if (string.IsNullOrEmpty(refreshToken))
                {
                    CookieHelper.ClearAuthCookies(context.Response, isProduction);
                    var badRequest = ApiResponse<AuthResponseWithCookiesDto>.FailureResult("Refresh token not found");
                    await scope.CompleteAndCommitAsync(
                        StatusCodes.Status400BadRequest,
                        badRequest,
                        idempotencyService,
                        cancellationToken,
                        context.Response);
                    return Results.BadRequest(badRequest);
                }

                var response = await mediator.Send(new RefreshTokenCommandRequest
                {
                    RefreshTokenCommandRequestDto = new RefreshTokenCommandDto
                    {
                        RefreshToken = refreshToken,
                        IpAddress = ipAddress
                    }
                }, cancellationToken);

                if (!response.Result.IsSuccess)
                {
                    CookieHelper.ClearAuthCookies(context.Response, isProduction);
                    var badRequest = ApiResponse<AuthResponseWithCookiesDto>.FailureResult(response.Result.Error!);
                    await scope.CompleteAndCommitAsync(
                        StatusCodes.Status400BadRequest,
                        badRequest,
                        idempotencyService,
                        cancellationToken,
                        context.Response);
                    return Results.BadRequest(badRequest);
                }

                if (response.Result.Value is null)
                {
                    CookieHelper.ClearAuthCookies(context.Response, isProduction);
                    var badRequest = ApiResponse<AuthResponseWithCookiesDto>.FailureResult("Token refresh failed: No response data");
                    await scope.CompleteAndCommitAsync(
                        StatusCodes.Status400BadRequest,
                        badRequest,
                        idempotencyService,
                        cancellationToken,
                        context.Response);
                    return Results.BadRequest(badRequest);
                }

                CookieHelper.SetAuthCookies(
                    context.Response,
                    response.Result.Value.AccessToken,
                    response.Result.Value.RefreshToken,
                    response.Result.Value.ExpiresAt,
                    isProduction);

                var result = ApiResponse<AuthResponseWithCookiesDto>.SuccessResult(new AuthResponseWithCookiesDto
                {
                    ExpiresAt = response.Result.Value.ExpiresAt,
                    User = response.Result.Value.User
                }, "Token refreshed");

                await scope.CompleteAndCommitAsync(
                    StatusCodes.Status200OK,
                    result,
                    idempotencyService,
                    cancellationToken,
                    context.Response);

                return Results.Ok(result);
            }
            catch
            {
                throw;
            }
        })
        .WithName("RefreshToken")
        .WithDescription("Refresh access token")
        .Produces<ApiResponse<AuthResponseWithCookiesDto>>(200)
        .Produces(400);

        // POST /api/v1/auth/logout
        group.MapPost("/logout", async (
            IUnitOfWork unitOfWork,
            HttpContext context,
            IIdempotencyService idempotencyService,
            ICurrentUserService currentUserService,
            IWebHostEnvironment environment,
            CancellationToken cancellationToken) =>
        {
            var refreshToken = context.Request.Cookies["refreshToken"];
            var isProduction = !environment.IsDevelopment();
            var requestHash = IdempotencyEndpointHelper.CreateHeaderOnlyRequestHash(
                "AuthLogout",
                refreshToken,
                CookieHelper.GetIpAddress(context));

            var (proceed, earlyReturn, idempotencyScope) = await IdempotencyEndpointHelper.TryBeginTransactionalSyncRequest(
                context,
                "AuthLogout",
                new
                {
                    HasRefreshToken = !string.IsNullOrWhiteSpace(refreshToken)
                },
                unitOfWork,
                idempotencyService,
                currentUserService,
                cancellationToken,
                requireIdempotencyKey: true,
                requestHash: requestHash);
            if (!proceed) return earlyReturn!;
            await using var scope = idempotencyScope;

            try
            {
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

                var result = ApiResponse<object>.SuccessResult(new { }, "Logged out successfully");
                await scope.CompleteAndCommitAsync(
                    StatusCodes.Status200OK,
                    result,
                    idempotencyService,
                    cancellationToken,
                    context.Response);

                return Results.Ok(result);
            }
            catch
            {
                throw;
            }
        })
        .WithName("Logout")
        .WithDescription("Logout and clear auth cookies")
        .Produces<ApiResponse<object>>(200);

        // GET /api/v1/auth/me
        group.MapGet("/me", async (
            IUnitOfWork unitOfWork,
            HttpContext context,
            CancellationToken cancellationToken) =>
        {
            var userIdClaim = context.User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            if (string.IsNullOrEmpty(userIdClaim) || !Guid.TryParse(userIdClaim, out var userId))
                return Results.Json(
                    ApiResponse<UserInfoDto>.FailureResult("User not authenticated or invalid user ID"),
                    statusCode: StatusCodes.Status401Unauthorized);

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

