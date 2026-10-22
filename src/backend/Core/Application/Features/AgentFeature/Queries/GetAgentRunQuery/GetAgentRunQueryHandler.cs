using System.Text.Json;
using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Data;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using BlogApp.Core.Domain.Enums;
using MediatR;
using Microsoft.EntityFrameworkCore;

namespace BlogApp.Core.Application.Features.AgentFeature.Queries.GetAgentRunQuery;

/// <summary>Terminal sonucun istemciye izin verilen sunumu (B10): snapshot'taki
/// answer/report/citations + kullanım özeti; makale kaynaklı sonuç sunum
/// denetiminden geçemezse maskelenir ve gerekçe taşınır (B8: "Yayından
/// kaldırılmış içeriğe dayanan sonucu ... sunmasın").</summary>
public sealed record AgentRunResultDto
{
    public required string Status { get; init; }

    public string? SelectedMode { get; init; }

    public string? SourceScope { get; init; }

    public string? Answer { get; init; }

    public string? Report { get; init; }

    public IReadOnlyList<AgentRunCitationDto> Citations { get; init; } = [];

    public string? UnresolvedQuestion { get; init; }

    /// <summary>v2 sonucun etkin niyeti (run_intent; örn. profile); v1 sonuçlarında null.</summary>
    public string? RunIntent { get; init; }

    /// <summary>Sunum denetimi sonucu sunumu engellediyse gerekçe: profil maskesinde
    /// <c>profile_updated</c> | <c>profile_unavailable</c> | <c>legacy_profile_unavailable</c> kodu,
    /// makale maskesinde açıklama cümlesi.</summary>
    public string? UnavailableReason { get; init; }

    /// <summary>Maskelemenin kullanıcıya gösterilecek açıklaması + yeni sorgu önerisi.</summary>
    public string? UnavailableMessage { get; init; }
}

/// <summary>Sonuç kaynağı. kind=profile kaynaklarında profile alanları dolar ve
/// <see cref="Url"/> yalnız canonical <c>/about#{sectionId}</c> olabilir (yeniden doğrulanır;
/// biçimi bozuk profile kaynağı düşürülür).</summary>
public sealed record AgentRunCitationDto(
    string Kind,
    string? Title,
    string? Url,
    Guid? ArticleId,
    long? ArticleRevision,
    int? ChunkIndex,
    string? SourceId,
    string? ProfileId = null,
    long? ProfileRevision = null,
    string? ProfileContentHash = null,
    string? SectionId = null);

/// <summary>
/// GET /api/v1/agent/runs/{runId} karşılığı (B10; plan tablosu: "Sahiplik
/// kontrolüyle durum ve izin verilen sonuç"). Sahiplik istek sahibinin
/// çözümlenmiş oturum anahtarıyla backend kaydı üzerinden doğrulanır; sonuç
/// makale kaynaklıysa <see cref="IAgentResultPresentationGuard"/> ile güncel
/// yayın erişimi denetlenir (B8 sunum kuralı; denetim cache KULLANMAZ).
/// </summary>
public sealed class GetAgentRunQueryHandler(
    IApplicationDbContext dbContext,
    ICurrentUserService currentUser,
    IAgentResultPresentationGuard presentationGuard) : IRequestHandler<GetAgentRunQueryRequest, Result<AgentRunStatusDto>>
{
    public async Task<Result<AgentRunStatusDto>> Handle(GetAgentRunQueryRequest request, CancellationToken cancellationToken)
    {
        var userId = currentUser.UserId;
        var guestSessionId = request.GuestSessionId?.Trim();
        if (userId is null && string.IsNullOrWhiteSpace(guestSessionId))
        {
            return Result<AgentRunStatusDto>.Failure(Error.Unauthorized("Agent işi için oturum gereklidir."));
        }

        var ownerKey = userId is not null ? $"u:{userId.Value:D}" : $"g:{guestSessionId}";

        var run = await dbContext.AgentRuns
            .AsNoTracking()
            .FirstOrDefaultAsync(r => r.Id == request.RunId, cancellationToken);
        if (run is null)
        {
            return Result<AgentRunStatusDto>.Failure(Error.NotFound("Agent işi bulunamadı."));
        }

        if (!string.Equals(run.OwnerKey, ownerKey, StringComparison.Ordinal))
        {
            return Result<AgentRunStatusDto>.Failure(Error.Forbidden("Bu agent işi başka bir oturuma ait."));
        }

        // Sunum denetimi yalnız terminal sonuçta anlamlıdır; projection kaydındaki
        // ResultJson asla ham haliyle dönmez — önce izin verilen alanlara ayrıştırılır.
        AgentRunResultDto? result = null;
        if (run.ResultJson is not null)
        {
            result = await BuildResultAsync(run, cancellationToken);
        }

        var wire = AgentRunWireContext.Parse(run.ContextSnapshotJson);

        return Result<AgentRunStatusDto>.Success(new AgentRunStatusDto
        {
            RunId = run.Id,
            ConversationId = run.ConversationId,
            TurnSequence = run.TurnSequence,
            Status = run.Status.ToString(),
            ModePreference = run.ModePreference,
            SelectedMode = run.SelectedMode,
            SourceScope = run.SourceScope,
            Question = run.Question,
            Language = run.Language,
            ArticleId = run.ArticleId,
            ConversationTopic = wire.ConversationTopic,
            WireVersion = wire.WireVersion,
            AcceptedAt = new DateTimeOffset(run.AcceptedAt, TimeSpan.Zero),
            DeadlineAt = new DateTimeOffset(run.DeadlineAt, TimeSpan.Zero),
            TerminalAt = run.TerminalAt is { } terminal
                ? new DateTimeOffset(terminal, TimeSpan.Zero)
                : null,
            LastEventSequence = run.LastEventSequence,
            Result = result,
        });
    }

    private async Task<AgentRunResultDto> BuildResultAsync(Core.Domain.Entities.AgentRun run, CancellationToken cancellationToken)
    {
        var context = new AgentRunResultContext(run.Id, run.ArticleId, run.ResultJson, run.ContextSnapshotJson);
        var presentation = await presentationGuard.CheckAsync(context, cancellationToken);

        if (!presentation.IsPresentable)
        {
            // Maskelenme kararı B10 sunum endpoint'inindir (guard yalnız okur):
            // sonuç içeriği DÖNMEZ, yalnız içerik kullanılamıyor gerekçesi taşınır.
            return new AgentRunResultDto
            {
                Status = run.Status.ToString(),
                SelectedMode = run.SelectedMode,
                SourceScope = run.SourceScope,
                UnavailableReason = presentation.UnavailableReason,
                UnavailableMessage = presentation.UnavailableMessage,
            };
        }

        return ParseResult(run, presentation.AvailableArticleIds);
    }

    public static AgentRunResultDto ParseResult(
        Core.Domain.Entities.AgentRun run, IReadOnlyList<Guid> availableArticleIds)
    {
        string? answer = null;
        string? report = null;
        string? unresolved = null;
        string? runIntent = null;
        var citations = new List<AgentRunCitationDto>();

        try
        {
            using var document = JsonDocument.Parse(run.ResultJson!);
            var root = document.RootElement;
            if (root.ValueKind == JsonValueKind.Object)
            {
                if (root.TryGetProperty("answer", out var answerElement) && answerElement.ValueKind == JsonValueKind.String)
                {
                    answer = answerElement.GetString();
                }

                if (root.TryGetProperty("report", out var reportElement) && reportElement.ValueKind == JsonValueKind.String)
                {
                    report = reportElement.GetString();
                }

                if (root.TryGetProperty("run_intent", out var intentElement) && intentElement.ValueKind == JsonValueKind.String)
                {
                    runIntent = intentElement.GetString();
                }

                if (root.TryGetProperty("unresolved_questions", out var unresolvedElement)
                    && unresolvedElement.ValueKind == JsonValueKind.Array)
                {
                    var first = unresolvedElement.EnumerateArray().FirstOrDefault();
                    if (first.ValueKind == JsonValueKind.String)
                    {
                        unresolved = first.GetString();
                    }
                }

                if (root.TryGetProperty("citations", out var citationsElement) && citationsElement.ValueKind == JsonValueKind.Array)
                {
                    foreach (var citation in citationsElement.EnumerateArray())
                    {
                        if (citation.ValueKind != JsonValueKind.Object)
                        {
                            continue;
                        }

                        var kind = citation.TryGetProperty("kind", out var kindElement) ? kindElement.GetString() : null;
                        Guid? articleId = null;
                        if (citation.TryGetProperty("article_id", out var articleIdElement)
                            && Guid.TryParse(articleIdElement.GetString(), out var parsed))
                        {
                            articleId = parsed;
                        }

                        // Makale kaynaklı atıf, sunum denetiminden geçmemiş makaleyi
                        // göstermez (savunma katmanı; guard zaten bozuk snapshot'ta da
                        // bağlam makalesini denetledi).
                        if (kind == "article" && articleId is { } id && !availableArticleIds.Contains(id))
                        {
                            continue;
                        }

                        if (kind == "profile")
                        {
                            // Profil kaynağı: URL modelden güvenilmez; canonical /about#{section_id}
                            // biçimi ve tutarlılığı yeniden doğrulanır, bozuk kaynak düşürülür.
                            if (ToProfileCitation(citation) is { } profileCitation)
                            {
                                citations.Add(profileCitation);
                            }

                            continue;
                        }

                        citations.Add(new AgentRunCitationDto(
                            kind ?? "web",
                            citation.TryGetProperty("title", out var titleElement) ? titleElement.GetString() : null,
                            citation.TryGetProperty("url", out var urlElement) ? urlElement.GetString() : null,
                            articleId,
                            citation.TryGetProperty("article_revision", out var revisionElement)
                                && revisionElement.TryGetInt64(out var revision)
                                ? revision
                                : null,
                            citation.TryGetProperty("chunk_index", out var chunkElement)
                                && chunkElement.TryGetInt32(out var chunk)
                                ? chunk
                                : null,
                            citation.TryGetProperty("source_id", out var sourceIdElement) ? sourceIdElement.GetString() : null));
                    }
                }
            }
        }
        catch (JsonException)
        {
            // Bozuk snapshot istemciye ham JSON olarak sızmaz; yalnız terminal durum taşınır.
        }

        return new AgentRunResultDto
        {
            Status = run.Status.ToString(),
            SelectedMode = run.SelectedMode,
            SourceScope = run.SourceScope,
            Answer = answer,
            Report = report,
            Citations = citations,
            UnresolvedQuestion = unresolved,
            RunIntent = runIntent,
        };
    }

    /// <summary>kind=profile kaynağını DTO'ya eşler; bölüm kimliği, canonical URL ve kaynak
    /// kimliği biçimi tutmazsa null (kaynak sunulmaz).</summary>
    public static AgentRunCitationDto? ToProfileCitation(JsonElement citation)
    {
        static string? Text(JsonElement element, string name) =>
            element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;

        static long? Long(JsonElement element, string name) =>
            element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var number)
                ? number
                : null;

        var profileId = Text(citation, "profile_id");
        var revision = Long(citation, "profile_revision");
        var hash = Text(citation, "profile_content_hash");
        var sectionId = Text(citation, "section_id");
        var chunk = Long(citation, "chunk_index");
        var url = Text(citation, "url");
        var sourceId = Text(citation, "source_id");
        if (profileId is null || revision is null || hash is null || sectionId is null || chunk is null
            || chunk.Value is < 0 or > int.MaxValue
            || !AgentContractFormats.IsValidProfileId(profileId)
            || !AgentContractFormats.IsValidHashHex(hash)
            || !AgentContractFormats.IsValidSectionId(sectionId)
            || url != AgentContractFormats.ComposeProfileUrl(sectionId)
            || sourceId != AgentContractFormats.ComposeProfileSourceId(profileId, revision.Value, hash, sectionId, chunk.Value))
        {
            return null;
        }

        return new AgentRunCitationDto(
            "profile",
            Text(citation, "title"),
            AgentContractFormats.ComposeProfileUrl(sectionId),
            ArticleId: null,
            ArticleRevision: null,
            ChunkIndex: (int)chunk.Value,
            SourceId: sourceId,
            ProfileId: profileId,
            ProfileRevision: revision,
            ProfileContentHash: hash,
            SectionId: sectionId);
    }
}
