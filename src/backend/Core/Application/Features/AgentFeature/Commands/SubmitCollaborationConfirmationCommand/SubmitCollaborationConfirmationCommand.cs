using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AgentFeature.Collaboration;
using MediatR;

namespace BlogApp.Core.Application.Features.AgentFeature.Commands.SubmitCollaborationConfirmationCommand;

/// <summary>Açık gönderim onayı isteği (B10 controller'ı çağırır). Sahiplik iddiası
/// burada TAŞINMAZ: owner, oturumdan çözülür (istemci owner alanı yetki kaynağı değildir).</summary>
public sealed record SubmitCollaborationConfirmationRequest : IRequest<Result<CollaborateSubmitResult>>
{
    public required Guid RunId { get; init; }

    public required Guid ProposalId { get; init; }

    /// <summary>Ziyaretçinin onayladığı (varsa düzenlediği) sürümün içerik hash'i.</summary>
    public required string SubmittedContentHash { get; init; }

    /// <summary>Düzenlenmiş özet; verildiyse onay YENİ SÜRÜM üzerindendir (plan B9).</summary>
    public string? EditedSummary { get; init; }

    /// <summary>Sunucu tarafı misafir oturumu; JWT kimliği yoksa zorunludur.</summary>
    public string? GuestSessionId { get; init; }
}

/// <summary>
/// Açık backend onay eylemi (plan B9: "Gönderim onayını açık backend eylemiyle al;
/// LLM metnindeki onay ifadesini yetkilendirme kaynağı yapma"). Oturumu çözer ve
/// onayı <see cref="AgentCollaborationService.SubmitConfirmationAsync"/>'e devreder;
/// LLM üretimi bu hattan GEÇMEZ — onayın tek kaynağı bu komutun çağrılmasıdır.
/// </summary>
public sealed class SubmitCollaborationConfirmationHandler(
    ICurrentUserService currentUser,
    AgentCollaborationService collaborationService)
    : IRequestHandler<SubmitCollaborationConfirmationRequest, Result<CollaborateSubmitResult>>
{
    public Task<Result<CollaborateSubmitResult>> Handle(
        SubmitCollaborationConfirmationRequest request,
        CancellationToken cancellationToken)
    {
        var ownerKey = ResolveOwnerKey(request.GuestSessionId);
        if (ownerKey is null)
        {
            return Task.FromResult(Result<CollaborateSubmitResult>.Failure(
                Error.Unauthorized("İş birliği onayı için oturum gereklidir.")));
        }

        return WrapAsync(ownerKey, request, cancellationToken);
    }

    private async Task<Result<CollaborateSubmitResult>> WrapAsync(
        string ownerKey,
        SubmitCollaborationConfirmationRequest request,
        CancellationToken cancellationToken)
    {
        var result = await collaborationService.SubmitConfirmationAsync(
            request.RunId,
            request.ProposalId,
            request.SubmittedContentHash,
            request.EditedSummary,
            ownerKey,
            DateTimeOffset.UtcNow,
            cancellationToken);

        // Sürümlü ret: bir sonraki katmana nedeni olduğu gibi taşır (HTTP eşlemesi
        // Presentation'ın işidir; bu fazda testler Result üstünden doğrular).
        return result.Outcome switch
        {
            CollaborateSubmitOutcome.Accepted => Result<CollaborateSubmitResult>.Success(result),
            CollaborateSubmitOutcome.Duplicate => Result<CollaborateSubmitResult>.Success(result),
            CollaborateSubmitOutcome.RejectedOwner => Result<CollaborateSubmitResult>.Failure(
                Error.Forbidden(result.RejectionReason ?? "bu çalışma başka bir oturuma ait")),
            CollaborateSubmitOutcome.RejectedVersion => Result<CollaborateSubmitResult>.Failure(
                Error.Conflict(result.RejectionReason ?? "öneri sürümü doğrulanamadı")),
            _ => Result<CollaborateSubmitResult>.Failure(Error.Domain("onay kaydedilemedi")),
        };
    }

    private string? ResolveOwnerKey(string? guestSessionId)
    {
        var userId = currentUser.UserId;
        var guest = guestSessionId?.Trim();
        if (userId is null && string.IsNullOrWhiteSpace(guest))
        {
            return null;
        }

        return userId is not null ? $"u:{userId.Value:D}" : $"g:{guest}";
    }
}
