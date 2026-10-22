using System.Net;
using System.Text.Json;
using Asp.Versioning;
using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Features.ProfileFeature.Queries.GetAuthorProfileQuery;
using BlogApp.Infrastructure.Services.AuthorProfile;
using BlogApp.Presentation.Api.Endpoints;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.Extensions.DependencyInjection;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.WhoAmI;

/// <summary>
/// GET /api/v1/profile ve /profile/snapshot (K6, A37): aktif + public + hash doğrulanmış profil
/// döner, yanıt <c>Cache-Control: no-store</c> taşır; profil kullanılamıyorsa 503 +
/// code profile_unavailable (gövde sunulmaz). DB/broker gerektirmez: mini WebApplication yalnız
/// endpoint + MediatR + profil kaynağı kaydeder (build çıktısındaki canonical kopya).
/// </summary>
public sealed class ProfileEndpointTests
{
    private sealed class FixedProfileSource(AuthorProfileState state) : IAuthorProfileSource
    {
        public AuthorProfileState GetCurrent() => state;
    }

    private static CancellationToken NewTestToken() => new CancellationTokenSource(TimeSpan.FromSeconds(60)).Token;

    private static WebApplication BuildHost(IAuthorProfileSource source)
    {
        var builder = WebApplication.CreateBuilder();
        builder.WebHost.UseUrls("http://127.0.0.1:0");
        builder.Services.AddSingleton(source);
        builder.Services.AddMediatR(cfg => cfg.RegisterServicesFromAssembly(typeof(GetAuthorProfileQueryHandler).Assembly));
        builder.Services.ConfigureHttpJsonOptions(options =>
            options.SerializerOptions.Converters.Add(new System.Text.Json.Serialization.JsonStringEnumConverter()));
        builder.Services.AddApiVersioning(options =>
        {
            options.DefaultApiVersion = new ApiVersion(1, 0);
            options.AssumeDefaultVersionWhenUnspecified = true;
            options.ReportApiVersions = true;
            options.ApiVersionReader = new UrlSegmentApiVersionReader();
        });

        var app = builder.Build();
        app.RegisterProfileEndpoints();
        return app;
    }

    [Fact]
    public async Task Handler_Returns_Canonical_Profile_When_Available()
    {
        var handler = new GetAuthorProfileQueryHandler(new FileAuthorProfileSource(FileAuthorProfileSource.ResolveDirectory(null)));

        var result = await handler.Handle(new GetAuthorProfileQueryRequest(), CancellationToken.None);

        Assert.True(result.IsSuccess, result.Error);
        Assert.Equal("berkay-kaplan", result.Value!.ProfileId);
        Assert.Equal("public", result.Value.Status);
        Assert.Contains(result.Value.Sections, s => s.SectionId == "education" && s.Title.En == "Education");
    }

    [Fact]
    public async Task Handler_Returns_Unavailable_When_Profile_Not_Public()
    {
        var handler = new GetAuthorProfileQueryHandler(new FixedProfileSource(
            AuthorProfileState.Unavailable(AuthorProfileAvailability.NotPublic, "geri çekildi")));

        var result = await handler.Handle(new GetAuthorProfileQueryRequest(), CancellationToken.None);

        Assert.True(result.IsFailure);
        Assert.Equal(ErrorCategory.Unavailable, result.ErrorDetail!.Category);
        Assert.Equal("profile_unavailable", result.ErrorDetail.Code);
    }

    [Fact]
    public async Task Endpoint_Serves_Profile_With_No_Store_And_Expected_Json_Shape()
    {
        var token = NewTestToken();
        await using var app = BuildHost(new FileAuthorProfileSource(FileAuthorProfileSource.ResolveDirectory(null)));
        await app.StartAsync(token);
        using var client = new HttpClient { BaseAddress = new Uri(app.Urls.First()) };

        using var response = await client.GetAsync("/api/v1/profile", token);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Contains("no-store", response.Headers.CacheControl!.ToString());
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(token));
        var data = document.RootElement.GetProperty("data");
        Assert.True(document.RootElement.GetProperty("success").GetBoolean());
        Assert.Equal("berkay-kaplan", data.GetProperty("profileId").GetString());
        Assert.Equal(1, data.GetProperty("revision").GetInt64());
        Assert.Matches("^[0-9a-f]{64}$", data.GetProperty("contentHash").GetString());
        Assert.Equal("Berkay Kaplan", data.GetProperty("ownerName").GetString());
        Assert.Equal("tr", data.GetProperty("language").GetString());
        Assert.Equal("public", data.GetProperty("status").GetString());

        var section = data.GetProperty("sections").EnumerateArray().First(s => s.GetProperty("sectionId").GetString() == "education");
        Assert.Equal("education", section.GetProperty("anchor").GetString());
        Assert.Equal("Eğitim", section.GetProperty("title").GetProperty("tr").GetString());
        Assert.Equal("historical", section.GetProperty("claim").GetProperty("temporal").GetString());
        Assert.Equal("2026-10-21", section.GetProperty("claim").GetProperty("asOf").GetString());
        Assert.Equal(JsonValueKind.Array, section.GetProperty("headingPath").ValueKind);

        var channels = data.GetProperty("contactChannels").EnumerateArray().ToList();
        Assert.Contains(channels, c => c.GetProperty("kind").GetString() == "github"
                                       && c.GetProperty("url").GetString() == "https://github.com/MrBekoX");
    }

    [Fact]
    public async Task Endpoint_Returns_503_No_Store_When_Profile_Unavailable()
    {
        var token = NewTestToken();
        await using var app = BuildHost(new FixedProfileSource(
            AuthorProfileState.Unavailable(AuthorProfileAvailability.HashMismatch, "hash")));
        await app.StartAsync(token);
        using var client = new HttpClient { BaseAddress = new Uri(app.Urls.First()) };

        foreach (var path in (string[])["/api/v1/profile", "/api/v1/profile/snapshot"])
        {
            using var response = await client.GetAsync(path, token);

            Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
            Assert.Contains("no-store", response.Headers.CacheControl!.ToString());
            using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(token));
            Assert.False(document.RootElement.GetProperty("success").GetBoolean());
            Assert.Equal("profile_unavailable", document.RootElement.GetProperty("code").GetString());
            Assert.Equal("Unavailable", document.RootElement.GetProperty("category").GetString());
            Assert.False(document.RootElement.TryGetProperty("data", out var data) && data.ValueKind != JsonValueKind.Null);
        }
    }

    [Fact]
    public async Task Snapshot_Endpoint_Returns_Metadata_Only()
    {
        var token = NewTestToken();
        await using var app = BuildHost(new FileAuthorProfileSource(FileAuthorProfileSource.ResolveDirectory(null)));
        await app.StartAsync(token);
        using var client = new HttpClient { BaseAddress = new Uri(app.Urls.First()) };

        using var response = await client.GetAsync("/api/v1/profile/snapshot", token);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Contains("no-store", response.Headers.CacheControl!.ToString());
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync(token));
        var data = document.RootElement.GetProperty("data");
        Assert.Equal("berkay-kaplan", data.GetProperty("profileId").GetString());
        Assert.False(data.TryGetProperty("sections", out _));
    }
}
