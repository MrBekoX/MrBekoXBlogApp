using Xunit;

namespace BlogApp.Presentation.Api.Tests.Messaging.Outbox;

/// <summary>
/// B3 test koleksiyonu: postgres test veritabanı fixture'ı paylaşılır ve broker
/// testleriyle sıraya alınır (B2 broker testleriyle eşzamanlı kuyruk erişimi yarış yapmasın).
/// </summary>
[CollectionDefinition("agent-rabbitmq-outbox")]
public sealed class AgentRabbitMqOutboxCollection : ICollectionFixture<AgentOutboxDatabaseFixture>
{
}

