namespace BlogApp.Core.Application.Common.Options;

/// <summary>
/// İş birliği onay/resume politikası (B9). appsettings.json "AgentCollaboration" section.
/// Süre sınırı backend politikasıdır: projection'ın kaydettiği her proposal sürümü
/// bu pencere içinde onaylanabilir; süresi geçen sürümün onayı reddedilir (plan B9:
/// "Proposal kimliği, içerik sürümü/hash'i, run sahipliği ve süre sınırı tut").
/// </summary>
public sealed class AgentCollaborationSettings
{
    public const string SectionName = "AgentCollaboration";

    /// <summary>Proposal sürümünün onay için geçerli kaldığı süre (varsayılan 7 gün).</summary>
    public int ProposalValidityHours { get; set; } = 168;
}
