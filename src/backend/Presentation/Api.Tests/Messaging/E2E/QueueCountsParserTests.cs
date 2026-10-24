using System.Text.Json;
using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.E2E;

public sealed class QueueCountsParserTests
{
    [Theory]
    [InlineData(0, 0)]
    [InlineData(2, 1)]
    public void ExplicitLiveCounters_ArePreserved(int ready, int unacked)
    {
        var output = JsonSerializer.Serialize(new[]
        {
            new { name = "test.events.q", messages_ready = ready, messages_unacknowledged = unacked },
        });

        Assert.Equal((ready, unacked), AgentE2eFixture.ParseQueueCounts(output, "test.events.q"));
    }

    [Theory]
    [InlineData("[]")]
    [InlineData("{}")]
    [InlineData("not-json")]
    [InlineData("[{\"name\":\"other.q\",\"messages_ready\":0,\"messages_unacknowledged\":0}]")]
    [InlineData("[{\"name\":\"test.events.q\",\"messages_ready\":0}]")]
    [InlineData("[{\"name\":\"test.events.q\",\"messages_unacknowledged\":0}]")]
    [InlineData("[{\"name\":\"test.events.q\",\"messages_ready\":\"0\",\"messages_unacknowledged\":0}]")]
    [InlineData("[{\"name\":\"test.events.q\",\"messages_ready\":-1,\"messages_unacknowledged\":0}]")]
    [InlineData("[{\"name\":\"test.events.q\",\"messages_ready\":0,\"messages_unacknowledged\":0},{\"name\":\"test.events.q\",\"messages_ready\":0,\"messages_unacknowledged\":0}]")]
    public void MissingOrInvalidLiveCounters_AreNotAnEmptyQueue(string output)
    {
        Assert.Throws<InvalidDataException>(() => AgentE2eFixture.ParseQueueCounts(output, "test.events.q"));
    }
}
