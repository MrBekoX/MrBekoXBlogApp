using System.Text.Json;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Diagnostics.HealthChecks;

namespace BlogApp.Presentation.Api.Health;

/// <summary>
/// /health/agent gövde yazıcısı (B11): varsayılan yalın "Healthy" metni yerine
/// her agent kontrolünün durumunu ve veri sözlüğünü JSON olarak taşır — outbox
/// backlog sayıları ve en eski bekleme yaşı böylece izleme sistemlerince
/// ayrıştırılabilir ("broker kapalıyken kabul edilen iş bekliyor" gösterimi,
/// plan satır 562). Sır içermeyen, yalnız gözlem verisi yazar.
/// </summary>
public static class AgentHealthResponseWriter
{
    private static readonly JsonSerializerOptions WriterOptions = new(JsonSerializerDefaults.Web);

    public static async Task WriteAsync(HttpContext context, HealthReport report)
    {
        context.Response.ContentType = "application/json; charset=utf-8";

        var payload = new Dictionary<string, object>
        {
            ["status"] = report.Status.ToString(),
            ["total_duration_ms"] = report.TotalDuration.TotalMilliseconds,
            ["entries"] = report.Entries.ToDictionary(
                entry => entry.Key,
                entry => new Dictionary<string, object?>
                {
                    ["status"] = entry.Value.Status.ToString(),
                    ["description"] = entry.Value.Description,
                    ["duration_ms"] = entry.Value.Duration.TotalMilliseconds,
                    ["data"] = entry.Value.Data,
                }),
        };

        await context.Response.WriteAsync(JsonSerializer.Serialize(payload, WriterOptions));
    }
}
