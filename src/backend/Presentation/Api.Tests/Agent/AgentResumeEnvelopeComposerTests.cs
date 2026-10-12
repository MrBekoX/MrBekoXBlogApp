using System.Text.Json;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Options;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Agent;

/// <summary>B10 zarf üreticisinin B1 sözleşme doğrulayıcısıyla birebir uyumu
/// (B3 deseni: commit öncesi doğrulama; geçersiz zarf komut üretmez).</summary>
public class AgentResumeEnvelopeComposerTests
{
    [Fact]
    public void ComposeResumeRequested_PassesContractValidator()
    {
        var (envelopeJson, messageId) = AgentResumeEnvelopeComposer.ComposeResumeRequested(
            Guid.NewGuid(),
            Guid.NewGuid(),
            correlationId: Guid.NewGuid().ToString("D"),
            occurredAt: DateTimeOffset.UtcNow,
            producer: "backend-net",
            checkpointReference: "checkpoint/attempt/1",
            userRef: "u:00000000-0000-0000-0000-000000000001");

        Assert.NotEqual(Guid.Empty.ToString("D"), messageId);
        Assert.Contains("agent.resume.requested", envelopeJson);

        var result = new AgentContractValidator(new AgentMessagingSettings()).Validate(envelopeJson);
        Assert.True(result.IsValid, $"validator reddetti: {result.Error?.Field} {result.Error?.Message}");
    }
}
