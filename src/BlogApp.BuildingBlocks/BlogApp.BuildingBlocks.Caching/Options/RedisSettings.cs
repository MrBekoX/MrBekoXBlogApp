namespace BlogApp.BuildingBlocks.Caching.Options;

/// <summary>
/// Redis connection settings for cache services
/// </summary>
public class RedisSettings
{
    public const string SectionName = "Redis";

    /// <summary>
    /// Redis connection string (e.g., "localhost:6379" or "redis:6379,password=xxx")
    /// </summary>
    public string ConnectionString { get; set; } = "localhost:6379";

    /// <summary>
    /// Instance name prefix for cache keys
    /// </summary>
    public string InstanceName { get; set; } = "BlogApp_";

    /// <summary>
    /// Enable/disable Redis caching (falls back to in-memory if disabled)
    /// </summary>
    public bool Enabled { get; set; } = true;

    /// <summary>
    /// Default cache expiration in minutes
    /// </summary>
    public int DefaultExpirationMinutes { get; set; } = 60;
}
