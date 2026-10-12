using BlogApp.Core.Application.Common.Errors;
using BlogApp.Core.Application.Common.Interfaces.Services;
using BlogApp.Core.Application.Common.Models;
using BlogApp.Core.Application.Features.AgentFeature.Collaboration;
using MediatR;

namespace BlogApp.Core.Application.Features.AgentFeature.Commands.RequestCollaborationResumeCommand;

/// <summary>Onaylanmış iş birliği proposal'ı için devam isteği (B10 controller'ı çağırır).</summary>
public sealed record RequestCollaborationResumeRequest : IRequest<Result<CollaborateResumeResult>>
{
    public required Guid RunId { get; init; }

    public required Guid ProposalId { get; init; }

    /// <summary>İstemcinin gördüğü onaylı sürümün hash'i; onaylanan sürümle eşleşmezse istek reddedilir.</summary>
    public required string ExpectedContentHash { get; init; }

    public string? GuestSessionId { get; init; }
}

/// <summary>
/// Düzenleme/ek açıklama sonucunu resume mesajına çeviren açık eylem (plan B9).
/// Oturumu çözer ve <see cref="AgentCollaborationService.ResumeRequestAsync"/>'e
/// devreder; ikinci resume isteği YENİ mesaj üretmez (Duplicate).
/// </summary>
public sealed class RequestCollaborationResumeHandler(
    ICurrentUserService currentUser,
    AgentCollaborationService collaborationService)
    : IRequestHandler<RequestCollaborationResumeRequest, Result<CollaborateResumeResult>>
{
    public Task<Result<CollaborateResumeResult>> Handle(
        RequestCollaborationResumeRequest request,
        CancellationToken cancellationToken)
    {
        var ownerKey = ResolveOwnerKey(request.GuestSessionId);
        if (ownerKey is null)
        {
            return Task.FromResult(Result<CollaborateResumeResult>.Failure(
                Error.Unauthorized("Devam isteği için oturum gereklidir.")));
        }

        return WrapAsync(ownerKey, request, cancellationToken);
    }

    private async Task<Result<CollaborateResumeResult>> WrapAsync(
        string ownerKey,
        RequestCollaborationResumeRequest request,
        CancellationToken cancellationToken)
    {
        var result = await collaborationService.ResumeRequestAsync(
            request.RunId,
            request.ProposalId,
            request.ExpectedContentHash,
            ownerKey,
            cancellationToken);

        return result.Outcome switch
        {
            CollaborateResumeOutcome.Sent => Result<CollaborateResumeResult>.Success(result),
            CollaborateResumeOutcome.Duplicate => Result<CollaborateResumeResult>.Success(result),
            CollaborateResumeOutcome.RejectedOwner => Result<CollaborateResumeResult>.Failure(
                Error.Forbidden(result.RejectionReason ?? "bu çalışma başka bir oturuma ait")),
            CollaborateResumeOutcome.RejectedVersion => Result<CollaborateResumeResult>.Failure(
                Error.Conflict(result.RejectionReason ?? "devam isteği doğrulanamadı")),
            _ => Result<CollaborateResumeResult>.Failure(Error.Domain("devam isteği kaydedilemedi")),
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
