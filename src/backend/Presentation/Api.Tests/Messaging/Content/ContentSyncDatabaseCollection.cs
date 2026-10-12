using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Content;

/// <summary>
/// B8 test koleksiyonu: scratch DB fixture'ı paylaşılır (L009: kendi scratch DB'si
/// blogdb_b8tests; diğer fazların DB/broker kaynaklarıyla paylaşımlı çalışmaz).
/// </summary>
[CollectionDefinition("agent-content-sync-b8")]
public sealed class ContentSyncDatabaseCollection : ICollectionFixture<ContentSyncDatabaseFixture>
{
}
