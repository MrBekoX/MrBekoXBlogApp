using System.Text.Json;
using BlogApp.Core.Application.Common.Messaging;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.WhoAmI;

/// <summary>
/// K4 all-run-v2: her backend run komutu üreticisi run'ın wire sürümüyle compose eder; üretilen zarf
/// kendi sürümünün sözleşmesinden geçer ve routing key registry'den türetilir. İçerik olayları v1 kalır.
/// </summary>
public sealed class AgentEnvelopeComposerVersionTests
{
    private static readonly Guid RunId = Guid.Parse("aaaaaaa1-0000-4000-8000-000000000001");
    private static readonly Guid ConversationId = Guid.Parse("bbbbbbb1-0000-4000-8000-000000000002");
    private const string Correlation = "ccccccc1-0000-4000-8000-000000000003";
    private static readonly DateTimeOffset Now = new(2026, 10, 22, 9, 0, 0, TimeSpan.Zero);

    private readonly AgentContractValidator _validator = new();

    public static TheoryData<int> Versions() => new() { 1, 2 };

    private void AssertValid(string json, int version, string messageType)
    {
        var result = _validator.Validate(json);
        Assert.True(result.IsValid, result.Error?.ToString());
        Assert.Equal(version, result.Envelope!.SchemaVersion);
        Assert.Equal(messageType, result.Envelope.MessageType);
        Assert.Equal($"{messageType}.v{version}", AgentMessageTypeRegistry.RoutingKeyFor(version, messageType));
    }

    [Fact]
    public void Execute_V1_Keeps_Frozen_Shape()
    {
        var (json, _) = AgentCommandEnvelopeComposer.ComposeExecutionRequested(
            RunId, ConversationId, Correlation, Now, Now.AddMinutes(5), "backend-net", "u:1",
            "Bu makale ne anlatıyor?", "tr", "auto", "standard", "agent-run/x/turn/1", null);

        AssertValid(json, 1, AgentMessageTypes.ExecutionRequested);
        using var document = JsonDocument.Parse(json);
        var payload = document.RootElement.GetProperty("payload");
        Assert.False(payload.TryGetProperty("conversation_topic", out _));
        Assert.False(payload.TryGetProperty("profile_snapshot", out _));
    }

    [Fact]
    public void Execute_V1_Rejects_V2_Only_Arguments()
    {
        Assert.Throws<ArgumentException>(() => AgentCommandEnvelopeComposer.ComposeExecutionRequested(
            RunId, ConversationId, Correlation, Now, Now.AddMinutes(5), "backend-net", "u:1",
            "soru", "tr", "auto", "standard", null, null, conversationTopic: "auto"));
    }

    [Fact]
    public void Execute_V2_Requires_Topic()
    {
        Assert.Throws<ArgumentException>(() => AgentCommandEnvelopeComposer.ComposeExecutionRequested(
            RunId, ConversationId, Correlation, Now, Now.AddMinutes(5), "backend-net", "u:1",
            "soru", "tr", "auto", "standard", null, null, schemaVersion: 2));
    }

    [Fact]
    public void Execute_V2_WhoAmI_Carries_Pinned_Snapshot_And_History()
    {
        var history = new List<AgentConversationTurn>
        {
            new() { Role = "user", Content = "Berkay kimdir?", CreatedAt = "2026-10-22T08:00:00.000Z" },
            new() { Role = "assistant", Content = "Berkay Kaplan bir yazılım geliştiricidir.", CreatedAt = "2026-10-22T08:00:05.000Z" },
        };

        var (json, _) = AgentCommandEnvelopeComposer.ComposeExecutionRequested(
            RunId, ConversationId, Correlation, Now, Now.AddMinutes(5), "backend-net", "g:guest",
            "Hangi üniversite?", "tr", "auto", "standard", "agent-run/x/turn/2", null,
            schemaVersion: 2,
            conversationTopic: "who_am_i",
            profileSnapshot: WhoAmITestData.Snapshot(),
            conversationHistory: history);

        AssertValid(json, 2, AgentMessageTypes.ExecutionRequested);
        Assert.True(_validator.TryValidateAs<AgentExecutionRequestedV2>(json, out _, out var payload, out var error), error?.ToString());
        Assert.Equal("who_am_i", payload!.ConversationTopic);
        Assert.True(payload.ProfileSnapshot!.SameAs(WhoAmITestData.Snapshot()));
        Assert.Equal(2, payload.ConversationHistory!.Count);
        Assert.Null(payload.ArticleId);
        Assert.Null(payload.SelectedText);
    }

    [Fact]
    public void Execute_V2_Auto_Without_Profile_Is_Valid()
    {
        var (json, _) = AgentCommandEnvelopeComposer.ComposeExecutionRequested(
            RunId, ConversationId, Correlation, Now, Now.AddMinutes(5), "backend-net", "u:1",
            "CQRS nedir?", "tr", "auto", "standard", null, null,
            articleId: "post-1", articleRevision: 3, articleContentHash: WhoAmITestData.Hash,
            schemaVersion: 2, conversationTopic: "auto");

        AssertValid(json, 2, AgentMessageTypes.ExecutionRequested);
    }

    [Theory]
    [MemberData(nameof(Versions))]
    public void Cancel_Uses_Run_Version(int version)
    {
        var (json, _) = AgentControlEnvelopeComposer.ComposeCancellationRequested(
            RunId, ConversationId, Correlation, Now, "backend-net", "kullanıcı iptali", version);

        AssertValid(json, version, AgentMessageTypes.CancellationRequested);
    }

    [Theory]
    [MemberData(nameof(Versions))]
    public void Resume_Uses_Run_Version(int version)
    {
        var (json, _) = AgentResumeEnvelopeComposer.ComposeResumeRequested(
            RunId, ConversationId, Correlation, Now, "backend-net", "agent-collab/x/proposal/y", "u:1", version);

        AssertValid(json, version, AgentMessageTypes.ResumeRequested);
    }

    [Theory]
    [MemberData(nameof(Versions))]
    public void Collaboration_Resume_And_ActionResult_Use_Run_Version(int version)
    {
        var proposalId = Guid.NewGuid();
        var (resume, _) = AgentCollaborationEnvelopeComposer.ComposeResumeRequested(
            RunId, ConversationId, Correlation, Now, "backend-net",
            AgentCollaborationEnvelopeComposer.ComposeCheckpointReference(RunId, proposalId), "u:1", version);
        AssertValid(resume, version, AgentMessageTypes.ResumeRequested);

        var (accepted, _) = AgentCollaborationEnvelopeComposer.ComposeActionResult(
            RunId, ConversationId, Correlation, Now, "backend-net", proposalId, "accepted", null, 4, Now,
            schemaVersion: version);
        AssertValid(accepted, version, AgentMessageTypes.ActionResult);

        var (rejected, messageId) = AgentCollaborationEnvelopeComposer.ComposeActionResult(
            RunId, ConversationId, Correlation, Now, "backend-net", proposalId, "rejected", "hash uyuşmadı", null, Now,
            deterministicMessageId: AgentCollaborationEnvelopeComposer.DeterministicRejectionMessageId(RunId, proposalId, WhoAmITestData.Hash),
            schemaVersion: version);
        AssertValid(rejected, version, AgentMessageTypes.ActionResult);
        Assert.Equal(AgentCollaborationEnvelopeComposer.DeterministicRejectionMessageId(RunId, proposalId, WhoAmITestData.Hash), messageId);
    }

    [Fact]
    public void Unsupported_Version_Produces_No_Command()
    {
        Assert.Throws<ArgumentException>(() => AgentControlEnvelopeComposer.ComposeCancellationRequested(
            RunId, ConversationId, Correlation, Now, "backend-net", null, schemaVersion: 3));
    }

    [Fact]
    public void Content_Events_Stay_On_V1()
    {
        Assert.Equal(1, AgentMessageTypeRegistry.ContentSchemaVersion);
        Assert.Equal("content.article.changed.v1",
            AgentMessageTypeRegistry.RoutingKeyFor(AgentMessageTypeRegistry.ContentSchemaVersion, AgentMessageTypes.ArticleContentChanged));
        Assert.Throws<ArgumentException>(() => AgentMessageTypeRegistry.RoutingKeyFor(2, AgentMessageTypes.ArticleContentChanged));
    }
}
