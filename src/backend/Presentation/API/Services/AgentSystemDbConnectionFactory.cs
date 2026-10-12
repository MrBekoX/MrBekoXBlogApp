using System.Data.Common;
using BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentObservationsQuery;
using Npgsql;

namespace BlogApp.Presentation.Api.Services;

/// <summary>
/// B10 yönetim gözleminin Python ``agent`` şeması okumaları için kısa ömürlü
/// salt-okunur bağlantı üretimi. EF bağlamının paylaşılan bağlantısını KULLANMAZ —
/// gözlem sorguları kendi bağlantısını açar/kapatır (D011: şema sahipliği Python'da;
/// burada yalnız SELECT çalışır).
/// </summary>
public sealed class AgentSystemDbConnectionFactory(IConfiguration configuration) : IAgentSystemDbConnectionFactory
{
    public async Task<DbConnection> OpenConnectionAsync(CancellationToken cancellationToken = default)
    {
        var connectionString = configuration.GetConnectionString("DefaultConnection")
            ?? throw new InvalidOperationException(
                "Agent şeması gözlemi için bağlantı dizesi bulunamadı (ConnectionStrings:DefaultConnection).");

        var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(cancellationToken);
        return connection;
    }
}
