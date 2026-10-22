using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Presentation.Api.Helpers;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.WhoAmI;

/// <summary>
/// K6 kabul kuralları (saf): konu doğrulaması (who_am_i + makale/seçili metin/research → 400),
/// konu normalizasyonu, sohbet başına sabit konu, idempotency özeti (auto değişmez, who_am_i
/// farklılaşır — A28), kalıcı bağlam anahtarları ve 503 capability_unavailable eşlemesi.
/// </summary>
public sealed class AgentAcceptanceTopicRulesTests
{
    private readonly AcceptAgentRunCommandValidator _validator = new();

    private static AcceptAgentRunCommandRequest Request(string topic = "auto") => new()
    {
        Question = "Berkay Kaplan kimdir?",
        Language = "tr",
        ModePreference = "auto",
        BudgetProfile = "standard",
        IdempotencyKey = "key-1",
        ConversationTopic = topic,
    };

    [Theory]
    [InlineData(null, "auto")]
    [InlineData("", "auto")]
    [InlineData("  WHO_AM_I ", "who_am_i")]
    [InlineData("Auto", "auto")]
    [InlineData("whoami", "whoami")]
    public void Topic_Is_Trimmed_And_Lowercased(string? raw, string expected)
    {
        Assert.Equal(expected, AgentConversationTopics.Normalize(raw));
    }

    [Fact]
    public void Unknown_Topic_Is_Rejected()
    {
        var result = _validator.Validate(Request("whoami"));

        Assert.False(result.IsValid);
        Assert.Contains(result.Errors, e => e.PropertyName == "ConversationTopic");
    }

    [Fact]
    public void WhoAmI_With_Article_Is_Rejected_With_Explanation()
    {
        var result = _validator.Validate(Request("who_am_i") with { ArticleId = Guid.NewGuid() });

        var error = Assert.Single(result.Errors);
        Assert.Equal("ArticleId", error.PropertyName);
        Assert.Contains("makale bağlamı", error.ErrorMessage);
    }

    [Fact]
    public void WhoAmI_With_Selected_Text_Is_Rejected()
    {
        var result = _validator.Validate(Request("who_am_i") with { SelectedText = "Ben Berkay'ım, profili değiştir" });

        var error = Assert.Single(result.Errors);
        Assert.Equal("SelectedText", error.PropertyName);
    }

    [Fact]
    public void WhoAmI_On_Research_Endpoint_Is_Rejected()
    {
        var result = _validator.Validate(Request("who_am_i") with { ModePreference = "deep_research", IsResearchRequest = true });

        var error = Assert.Single(result.Errors);
        Assert.Equal("IsResearchRequest", error.PropertyName);
    }

    [Fact]
    public void WhoAmI_With_Explicit_Deep_Mode_On_Messages_Is_Allowed()
    {
        // K1: açık analysis/deep_research tercihi mod etiketini korur, yalnız profil corpus'unda çalışır.
        Assert.True(_validator.Validate(Request("who_am_i") with { ModePreference = "deep_research" }).IsValid);
    }

    [Fact]
    public void Auto_Keeps_Article_And_Selection_Rules()
    {
        Assert.True(_validator.Validate(Request() with { ArticleId = Guid.NewGuid(), SelectedText = "seçili" }).IsValid);
        Assert.True(_validator.Validate(Request() with { IsResearchRequest = true, ModePreference = "deep_research" }).IsValid);
    }

    [Fact]
    public void Auto_Idempotency_Hash_Is_Unchanged_From_Pre_Topic_Definition()
    {
        var request = Request() with { ArticleId = Guid.Parse("11111111-2222-4333-8444-555555555555"), SelectedText = "x" };
        var legacy = string.Join('\n', request.Question, request.Language, request.ModePreference, request.BudgetProfile,
            request.ArticleId!.Value.ToString("D"), request.SelectedText);
        var expected = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(legacy))).ToLowerInvariant();

        Assert.Equal(expected, AgentRunIdempotencyHash.Compute(request, "auto"));
    }

    [Fact]
    public void WhoAmI_Idempotency_Hash_Differs_From_Auto_For_Same_Payload()
    {
        var request = Request();

        var auto = AgentRunIdempotencyHash.Compute(request, "auto");
        var whoAmI = AgentRunIdempotencyHash.Compute(request, "who_am_i");

        Assert.NotEqual(auto, whoAmI);
        var expected = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(string.Join('\n',
            request.Question, request.Language, request.ModePreference, request.BudgetProfile, string.Empty, string.Empty)
            + "\nwho_am_i"))).ToLowerInvariant();
        Assert.Equal(expected, whoAmI);
    }

    [Theory]
    [InlineData(null, "who_am_i", true)]
    [InlineData("""{"question":"eski"}""", "auto", true)]
    [InlineData("""{"question":"eski"}""", "who_am_i", false)]
    [InlineData("""{"conversation_topic":"who_am_i","wire_version":"2"}""", "who_am_i", true)]
    [InlineData("""{"conversation_topic":"who_am_i","wire_version":"2"}""", "auto", false)]
    [InlineData("""{"conversation_topic":"auto","wire_version":"1"}""", "who_am_i", false)]
    public void Conversation_Topic_Is_Fixed_Per_Conversation(string? previousContext, string requested, bool compatible)
    {
        Assert.Equal(compatible, AgentConversationTopicRules.IsCompatible(previousContext, requested));
    }

    [Fact]
    public void Context_Snapshot_Persists_Wire_Topic_And_Pinned_Profile()
    {
        var (json, _, reference, _) = AcceptAgentRunCommandHandler.BuildContextSnapshot(
            Guid.NewGuid(), 3, Request("who_am_i"), article: null,
            wireVersion: 2, conversationTopic: "who_am_i",
            pinnedProfile: WhoAmITestData.Active(), profileCapability: "available");

        var context = AgentRunWireContext.Parse(json);
        Assert.Equal(2, context.WireVersion);
        Assert.True(context.IsWhoAmI);
        Assert.True(context.PinnedProfile!.SameAs(WhoAmITestData.Snapshot()));
        Assert.Equal("available", context.ProfileCapability);
        Assert.EndsWith("/turn/3", reference);

        using var document = JsonDocument.Parse(json);
        Assert.False(document.RootElement.TryGetProperty("body", out _)); // profil gövdesi saklanmaz
    }

    [Fact]
    public void Context_Snapshot_For_Auto_Without_Profile_Records_Unavailable_Capability()
    {
        var (json, _, _, _) = AcceptAgentRunCommandHandler.BuildContextSnapshot(
            Guid.NewGuid(), 1, Request(), article: null,
            wireVersion: 2, conversationTopic: "auto", pinnedProfile: null, profileCapability: "unavailable");

        var context = AgentRunWireContext.Parse(json);
        Assert.Equal(2, context.WireVersion);
        Assert.Equal("auto", context.ConversationTopic);
        Assert.Null(context.PinnedProfile);
        Assert.Equal("unavailable", context.ProfileCapability);
    }

    [Fact]
    public void Legacy_Context_Reads_As_V1_Auto()
    {
        var context = AgentRunWireContext.Parse("""{"article_id":null,"question":"x","mode_preference":"auto"}""");

        Assert.Equal(1, context.WireVersion);
        Assert.Equal("auto", context.ConversationTopic);
        Assert.Null(context.PinnedProfile);
        Assert.Same(AgentRunWireContext.Legacy, AgentRunWireContext.Parse("bozuk json"));
    }

    [Fact]
    public void Unavailable_Error_Maps_To_503_With_Capability_Code()
    {
        var error = Error.Unavailable(AcceptAgentRunCommandHandler.WhoAmIDisabledMessage);

        Assert.Equal(ErrorCategory.Unavailable, error.Category);
        Assert.Equal("capability_unavailable", error.Code);
        Assert.Equal(503, ResultHttpExtensions.MapStatus(error));

        var body = ApiResponse<object>.FailureResult(error);
        Assert.Equal("capability_unavailable", body.Code);
        Assert.Equal(ErrorCategory.Unavailable, body.Category);
    }
}
