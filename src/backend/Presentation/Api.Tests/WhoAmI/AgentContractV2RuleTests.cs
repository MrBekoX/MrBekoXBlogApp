using System.Text.Json.Nodes;
using BlogApp.Core.Application.Common.Messaging;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.WhoAmI;

/// <summary>
/// v2 çapraz kuralları (fixture setinin kapsamadığı dallar): source_reference tür bazlı
/// zorunlu/yasak alanlar, profile kaynağının snapshot'sız taşınması, mode_selected profile kuralları,
/// sürüm karışması (v2 alanı v1 zarfında) ve v1 davranışının korunması.
/// </summary>
public sealed class AgentContractV2RuleTests
{
    private readonly AgentContractValidator _validator = new();

    private static JsonObject Completed(string runIntent, string sourceScope, params JsonObject[] citations) =>
        JsonNode.Parse(WhoAmITestData.ResultJson(runIntent, sourceScope, citations: citations))!.AsObject();

    [Fact]
    public void Valid_Profile_Completed_Passes()
    {
        var json = WhoAmITestData.Envelope(2, AgentMessageTypes.RunCompleted, Completed("profile", "profile", WhoAmITestData.ProfileCitation()));

        var result = _validator.Validate(json);

        Assert.True(result.IsValid, result.Error?.ToString());
    }

    [Fact]
    public void Article_Citation_Cannot_Carry_Profile_Fields()
    {
        var citation = WhoAmITestData.ArticleCitation(Guid.NewGuid());
        citation["section_id"] = "education";
        var payload = Completed("article_qa", "article", citation);
        payload.Remove("profile_snapshot");

        var result = _validator.Validate(WhoAmITestData.Envelope(2, AgentMessageTypes.RunCompleted, payload));

        Assert.Equal(AgentContractErrorCategory.WrongType, result.Error!.Category);
        Assert.Contains("section_id", result.Error.Field);
    }

    [Fact]
    public void Web_Citation_Requires_Accessed_At()
    {
        var web = new JsonObject { ["kind"] = "web", ["url"] = "https://example.com/x" };
        var payload = Completed("research", "web", web);
        payload.Remove("profile_snapshot");

        var result = _validator.Validate(WhoAmITestData.Envelope(2, AgentMessageTypes.RunCompleted, payload));

        Assert.Equal(AgentContractErrorCategory.MissingField, result.Error!.Category);
        Assert.Contains("accessed_at", result.Error.Field);
    }

    [Fact]
    public void Profile_Citation_Requires_Section_Id()
    {
        var citation = WhoAmITestData.ProfileCitation();
        citation.Remove("section_id");

        var result = _validator.Validate(WhoAmITestData.Envelope(2, AgentMessageTypes.RunCompleted,
            Completed("profile", "profile", citation)));

        Assert.Equal(AgentContractErrorCategory.MissingField, result.Error!.Category);
        Assert.Contains("section_id", result.Error.Field);
    }

    [Fact]
    public void Profile_Citation_Without_Payload_Snapshot_Is_Bad_Format()
    {
        // run_intent general + profile kaynağı + snapshot yok: kaynak pinlenmiş sürüme bağlanamaz.
        var payload = Completed("general", "general", WhoAmITestData.ProfileCitation());
        payload.Remove("profile_snapshot");

        var result = _validator.Validate(WhoAmITestData.Envelope(2, AgentMessageTypes.RunCompleted, payload));

        Assert.Equal(AgentContractErrorCategory.BadFormat, result.Error!.Category);
    }

    [Fact]
    public void Profile_Partial_With_Article_Citation_Is_Rejected()
    {
        var payload = Completed("profile", "profile", WhoAmITestData.ProfileCitation(), WhoAmITestData.ArticleCitation(Guid.NewGuid()));

        var result = _validator.Validate(WhoAmITestData.Envelope(2, AgentMessageTypes.RunPartiallyCompleted, payload));

        Assert.Equal(AgentContractErrorCategory.WrongType, result.Error!.Category);
        Assert.Contains("kind", result.Error.Field);
    }

    [Fact]
    public void Profile_Section_Id_Must_Match_Pattern()
    {
        var citation = WhoAmITestData.ProfileCitation();
        citation["section_id"] = "Education_Section";

        var result = _validator.Validate(WhoAmITestData.Envelope(2, AgentMessageTypes.RunCompleted,
            Completed("profile", "profile", citation)));

        Assert.Equal(AgentContractErrorCategory.BadFormat, result.Error!.Category);
    }

    [Fact]
    public void Mode_Selected_Profile_Requires_Profile_Scope_And_Snapshot()
    {
        var wrongScope = new JsonObject
        {
            ["event_sequence"] = 2,
            ["selected_mode"] = "fast",
            ["requires_web_search"] = false,
            ["reason"] = "profil",
            ["run_intent"] = "profile",
            ["source_scope"] = "article",
            ["profile_snapshot"] = new JsonObject { ["profile_id"] = "sample-author", ["revision"] = 1, ["content_hash"] = WhoAmITestData.Hash },
        };
        var missingSnapshot = (JsonObject)wrongScope.DeepClone();
        missingSnapshot["source_scope"] = "profile";
        missingSnapshot.Remove("profile_snapshot");

        Assert.Equal(AgentContractErrorCategory.WrongType,
            _validator.Validate(WhoAmITestData.Envelope(2, AgentMessageTypes.RunModeSelected, wrongScope)).Error!.Category);
        Assert.Equal(AgentContractErrorCategory.MissingField,
            _validator.Validate(WhoAmITestData.Envelope(2, AgentMessageTypes.RunModeSelected, missingSnapshot)).Error!.Category);
    }

    [Fact]
    public void Failed_Without_Run_Intent_Is_Valid_Under_V2()
    {
        var payload = new JsonObject { ["event_sequence"] = 3, ["error_code"] = "config_error", ["error_message"] = "profil kaynağı yok" };

        var result = _validator.Validate(WhoAmITestData.Envelope(2, AgentMessageTypes.RunFailed, payload));

        Assert.True(result.IsValid, result.Error?.ToString());
    }

    [Fact]
    public void V2_Field_Under_V1_Envelope_Is_Extra_Field()
    {
        var payload = new JsonObject
        {
            ["user_ref"] = "u:1",
            ["question"] = "Sample kimdir?",
            ["language"] = "tr",
            ["mode_preference"] = "auto",
            ["budget_profile"] = "standard",
            ["conversation_topic"] = "auto",
        };

        var result = _validator.Validate(WhoAmITestData.Envelope(1, AgentMessageTypes.ExecutionRequested, payload, "backend-net", withDeadline: true));

        Assert.Equal(AgentContractErrorCategory.ExtraField, result.Error!.Category);
    }

    [Fact]
    public void Profile_Citation_Kind_Is_Unknown_Under_V1()
    {
        var payload = JsonNode.Parse(WhoAmITestData.ResultJson(citations: [new JsonObject { ["kind"] = "profile", ["title"] = "x" }]))!.AsObject();
        payload.Remove("run_intent");
        payload.Remove("profile_snapshot");

        var result = _validator.Validate(WhoAmITestData.Envelope(1, AgentMessageTypes.RunCompleted, payload));

        Assert.Equal(AgentContractErrorCategory.WrongType, result.Error!.Category);
    }

    [Fact]
    public void V1_Article_Citation_Behavior_Is_Unchanged()
    {
        // v1'de tür bazlı alan ayrımı doğrulayıcıda yoktur (donuk davranış); v2 kuralları sızmaz.
        var citation = new JsonObject { ["kind"] = "article", ["article_id"] = "my-post", ["url"] = "/posts/x" };
        var payload = JsonNode.Parse(WhoAmITestData.ResultJson(sourceScope: "article", citations: [citation]))!.AsObject();
        payload.Remove("run_intent");
        payload.Remove("profile_snapshot");

        var result = _validator.Validate(WhoAmITestData.Envelope(1, AgentMessageTypes.RunCompleted, payload));

        Assert.True(result.IsValid, result.Error?.ToString());
    }
}
