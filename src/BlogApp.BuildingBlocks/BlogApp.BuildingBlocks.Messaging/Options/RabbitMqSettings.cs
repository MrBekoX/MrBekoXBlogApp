namespace BlogApp.BuildingBlocks.Messaging.Options;

/// <summary>
/// RabbitMQ connection settings
/// </summary>
public class RabbitMqSettings
{
    public const string SectionName = "RabbitMQ";

    public string HostName { get; set; } = "localhost";
    public int Port { get; set; } = 5672;
    public string UserName { get; set; } = "guest";
    public string Password { get; set; } = "guest";
    public string VirtualHost { get; set; } = "/";
    public string ExchangeName { get; set; } = "blog.events";
    public bool Enabled { get; set; } = true;

    /// <summary>
    /// Number of messages the broker will deliver to the consumer before requiring an ack.
    /// Higher values improve throughput; lower values reduce memory pressure and improve
    /// fairness across consumers. Default: 10.
    /// </summary>
    public ushort PrefetchCount { get; set; } = 10;
}
