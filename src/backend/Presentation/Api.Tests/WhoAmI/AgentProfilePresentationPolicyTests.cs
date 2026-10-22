using System.Text.Json;
using System.Text.Json.Nodes;
using BlogApp.Core.Application.Common.AuthorProfile;
using BlogApp.Core.Application.Common.Options;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunQuery;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using Microsoft.Extensions.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.WhoAmI;

/// <summary>
/// K6 tek sunum politikası (GET/SignalR/replay/geçmiş): profil sonucunun aktif snapshot ile
/// eşleşmesi, provenance tutarlılığı, legacy v1 profil maskesi ve AUTO→PROFILE'da bağlam makalesinin
/// sunum bağımlılığı olmaması. Guard'ın DB'ye gitmeyen dalları gerçek guard üzerinde koşulur
/// (DbContext null: DB'ye dokunulsaydı test NullReference ile düşerdi).
/// </summary>
public sealed class AgentProfilePresentationPolicyTests
{
    private static readonly AgentRunWireContext WhoAmIContext =
        AgentRunWireContext.Parse(WhoAmITestData.ContextJson(2, "who_am_i", WhoAmITestData.Snapshot()));

    private static readonly AgentRunWireContext AutoPinnedContext =
        AgentRunWireContext.Parse(WhoAmITestData.ContextJson(2, "auto", WhoAmITestData.Snapshot()));

    private static AgentProfilePresentationDecision Evaluate(
        AgentRunWireContext context,
        string resultJson,
        AuthorProfileSnapshot? active = null,
        bool v2Enabled = true,
        bool useDefaultActive = true) =>
        AgentProfilePresentationPolicy.Evaluate(
            context,
            AgentResultFacts.Parse(resultJson),
            useDefaultActive ? active ?? WhoAmITestData.Active() : active,
            v2Enabled);

    [Fact]
    public void Verified_WhoAmI_Result_Is_Presentable_And_Not_Article_Dependent()
    {
        var decision = Evaluate(WhoAmIContext, WhoAmITestData.ResultJson());

        Assert.True(decision.ProfileGoverned);
        Assert.Equal(AgentPresentationMask.None, decision.Mask);
        Assert.True(decision.ExcludeContextArticle);
    }

    [Fact]
    public void Refusal_Without_Citations_Is_Presentable_With_Pinned_Snapshot()
    {
        var decision = Evaluate(WhoAmIContext, WhoAmITestData.ResultJson(citations: [], answer: "Bu bilgi profilde paylaşılmıyor."));

        Assert.Equal(AgentPresentationMask.None, decision.Mask);
    }

    [Fact]
    public void Updated_Profile_Revision_Masks_Old_Result()
    {
        var decision = Evaluate(WhoAmIContext, WhoAmITestData.ResultJson(), active: WhoAmITestData.Active(2, WhoAmITestData.OtherHash));

        Assert.Equal(AgentPresentationMask.ProfileUpdated, decision.Mask);
        Assert.Equal("profile_updated", AgentProfilePresentationPolicy.CodeOf(decision.Mask));
    }

    [Fact]
    public void Unavailable_Profile_Masks_Result()
    {
        var decision = Evaluate(WhoAmIContext, WhoAmITestData.ResultJson(), active: null, useDefaultActive: false);

        Assert.Equal(AgentPresentationMask.ProfileUnavailable, decision.Mask);
    }

    [Fact]
    public void Payload_Snapshot_Different_From_Pinned_Is_Masked()
    {
        var other = WhoAmITestData.Snapshot(2, WhoAmITestData.OtherHash);
        var decision = Evaluate(WhoAmIContext, WhoAmITestData.ResultJson(snapshot: other), active: WhoAmITestData.Active(2, WhoAmITestData.OtherHash));

        Assert.Equal(AgentPresentationMask.ProfileUnavailable, decision.Mask);
    }

    [Fact]
    public void WhoAmI_Result_Without_Profile_Intent_Is_Masked()
    {
        var decision = Evaluate(WhoAmIContext, WhoAmITestData.ResultJson(runIntent: "general", sourceScope: "general", citations: []));

        Assert.Equal(AgentPresentationMask.ProfileUnavailable, decision.Mask);
    }

    [Fact]
    public void Inconsistent_Profile_Citation_Is_Masked()
    {
        var citation = WhoAmITestData.ProfileCitation();
        citation["url"] = "https://evil.example/about#education";

        var decision = Evaluate(WhoAmIContext, WhoAmITestData.ResultJson(citations: [citation]));

        Assert.Equal(AgentPresentationMask.ProfileUnavailable, decision.Mask);
    }

    [Fact]
    public void Profile_Result_With_Article_Citation_Is_Masked()
    {
        var decision = Evaluate(AutoPinnedContext, WhoAmITestData.ResultJson(
            citations: [WhoAmITestData.ProfileCitation(), WhoAmITestData.ArticleCitation(Guid.NewGuid())]));

        Assert.Equal(AgentPresentationMask.ProfileUnavailable, decision.Mask);
    }

    [Fact]
    public void Source_Scope_Claim_Alone_Does_Not_Relax_Article_Guard()
    {
        // AUTO run: model source_scope=profile dedi ama run_intent profile değil → doğrulanmamış;
        // bağlam makalesi gevşetilmez (maskelenir; asla ExcludeContextArticle=true dönmez).
        var decision = Evaluate(AutoPinnedContext, WhoAmITestData.ResultJson(runIntent: "general", citations: []));

        Assert.NotEqual(AgentPresentationMask.None, decision.Mask);
        Assert.False(decision.ExcludeContextArticle);
    }

    [Fact]
    public void Auto_Article_Result_Is_Not_Profile_Governed()
    {
        var decision = Evaluate(AutoPinnedContext, WhoAmITestData.ResultJson(
            runIntent: "article_qa", sourceScope: "article", includeSnapshot: false,
            citations: [WhoAmITestData.ArticleCitation(Guid.NewGuid())]));

        Assert.Equal(AgentProfilePresentationDecision.NotGoverned, decision);
    }

    [Fact]
    public void Legacy_V1_Profile_Result_Is_Masked_Only_When_V2_Enabled()
    {
        var legacy = AgentRunWireContext.Parse("""{"question":"x"}""");
        var result = """{"event_sequence":3,"selected_mode":"fast","answer":"eski profil cevabı","source_scope":"profile","usage":{"run_id":"r","recorded_at":"2026-10-01T00:00:00Z"}}""";

        Assert.Equal(AgentPresentationMask.LegacyProfileUnavailable, Evaluate(legacy, result, v2Enabled: true).Mask);
        Assert.Equal(AgentProfilePresentationDecision.NotGoverned, Evaluate(legacy, result, v2Enabled: false));
        Assert.Equal("legacy_profile_unavailable", AgentProfilePresentationPolicy.CodeOf(AgentPresentationMask.LegacyProfileUnavailable));
    }

    [Fact]
    public void Failed_WhoAmI_Result_Has_No_Content_To_Mask()
    {
        var decision = Evaluate(WhoAmIContext, """{"event_sequence":4,"error_code":"config_error"}""");

        Assert.True(decision.ProfileGoverned);
        Assert.Equal(AgentPresentationMask.None, decision.Mask);
    }

    // ------------------------------------------------------------------ gerçek guard (DB'siz dallar)

    private sealed class FixedProfileSource(AuthorProfileState state) : IAuthorProfileSource
    {
        public AuthorProfileState GetCurrent() => state;
    }

    private static AuthorProfileState AvailableState(AuthorProfileSnapshot snapshot) =>
        new(AuthorProfileAvailability.Available, null, new AuthorProfileDocument(
            snapshot, "tr", "Sample Author", [], "public", true, null, [], []));

    private static AgentResultPresentationGuard Guard(AuthorProfileState state, bool v2Enabled = true) =>
        new(null!, new FixedProfileSource(state), Options.Create(new AgentWireV2Settings { Enabled = v2Enabled }));

    [Fact]
    public async Task Guard_Presents_Auto_To_Profile_Result_Without_Checking_Context_Article()
    {
        var guard = Guard(AvailableState(WhoAmITestData.Active()));
        var context = new AgentRunResultContext(
            Guid.NewGuid(),
            ArticleId: Guid.NewGuid(), // makale panelinden AUTO soruldu; makale kullanılmadı
            WhoAmITestData.ResultJson(),
            WhoAmITestData.ContextJson(2, "auto", WhoAmITestData.Snapshot()));

        var presentation = await guard.CheckAsync(context);

        Assert.True(presentation.IsPresentable);
        Assert.True(presentation.IsProfileResult);
        Assert.Null(presentation.UnavailableReason);
    }

    [Fact]
    public async Task Guard_Masks_Stale_Profile_With_Code_And_Suggestion()
    {
        var guard = Guard(AvailableState(WhoAmITestData.Active(2, WhoAmITestData.OtherHash)));
        var context = new AgentRunResultContext(
            Guid.NewGuid(), null, WhoAmITestData.ResultJson(), WhoAmITestData.ContextJson(2, "who_am_i", WhoAmITestData.Snapshot()));

        var presentation = await guard.CheckAsync(context);

        Assert.False(presentation.IsPresentable);
        Assert.Equal("profile_updated", presentation.UnavailableReason);
        Assert.Contains("yeniden sorun", presentation.UnavailableMessage);
    }

    [Fact]
    public async Task Guard_Masks_When_Profile_Source_Is_Unavailable()
    {
        var guard = Guard(AuthorProfileState.Unavailable(AuthorProfileAvailability.NotPublic, "geri çekildi"));
        var context = new AgentRunResultContext(
            Guid.NewGuid(), null, WhoAmITestData.ResultJson(), WhoAmITestData.ContextJson(2, "who_am_i", WhoAmITestData.Snapshot()));

        var presentation = await guard.CheckAsync(context);

        Assert.Equal("profile_unavailable", presentation.UnavailableReason);
    }

    [Fact]
    public void Article_Mask_Keeps_Existing_Message()
    {
        var presentation = new AgentResultPresentation
        {
            IsPresentable = false,
            UnavailableArticleIds = [Guid.NewGuid()],
            AvailableArticleIds = [],
        };

        Assert.Equal(AgentResultPresentation.ArticleUnavailableMessage, presentation.UnavailableReason);
        Assert.Equal(AgentResultPresentation.ArticleUnavailableMessage, presentation.UnavailableMessage);
    }

    // ------------------------------------------------------------------ citation DTO

    [Fact]
    public void Status_Dto_Maps_Profile_Citation_Fields_From_Canonical_Metadata()
    {
        using var document = JsonDocument.Parse(WhoAmITestData.ProfileCitation("teaching", 2).ToJsonString());

        var dto = GetAgentRunQueryHandler.ToProfileCitation(document.RootElement);

        Assert.NotNull(dto);
        Assert.Equal("profile", dto!.Kind);
        Assert.Equal("/about#teaching", dto.Url);
        Assert.Equal("teaching", dto.SectionId);
        Assert.Equal("sample-author", dto.ProfileId);
        Assert.Equal(1, dto.ProfileRevision);
        Assert.Equal(WhoAmITestData.Hash, dto.ProfileContentHash);
        Assert.Equal(2, dto.ChunkIndex);
        Assert.Null(dto.ArticleId);
    }

    [Theory]
    [InlineData("url", "https://evil.example/about#teaching")]
    [InlineData("url", "/about#education")]
    [InlineData("section_id", "Bad Section")]
    [InlineData("source_id", "profile:x")]
    public void Status_Dto_Drops_Malformed_Profile_Citation(string field, string value)
    {
        var citation = WhoAmITestData.ProfileCitation("teaching");
        citation[field] = value;
        using var document = JsonDocument.Parse(citation.ToJsonString());

        Assert.Null(GetAgentRunQueryHandler.ToProfileCitation(document.RootElement));
    }

    [Fact]
    public void Parse_Result_Keeps_Run_Intent_And_Profile_Citations()
    {
        var run = new BlogApp.Core.Domain.Entities.AgentRun
        {
            Status = BlogApp.Core.Domain.Enums.AgentRunStatus.Completed,
            ResultJson = WhoAmITestData.ResultJson(citations: [WhoAmITestData.ProfileCitation(), BadCitation()]),
        };

        var dto = GetAgentRunQueryHandler.ParseResult(run, []);

        Assert.Equal("profile", dto.RunIntent);
        var citation = Assert.Single(dto.Citations);
        Assert.Equal("/about#education", citation.Url);

        static JsonObject BadCitation()
        {
            var bad = WhoAmITestData.ProfileCitation("teaching");
            bad["url"] = "javascript:alert(1)";
            return bad;
        }
    }
}
