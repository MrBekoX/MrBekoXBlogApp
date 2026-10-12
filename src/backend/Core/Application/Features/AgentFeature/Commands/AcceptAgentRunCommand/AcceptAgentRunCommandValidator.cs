using BlogApp.Core.Application.Common.Messaging;
using FluentValidation;

namespace BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;

/// <summary>
/// Kabul komutunun giriş doğrulaması; kural kümesi B1 payload sözleşmesiyle aynıdır
/// (question ≤8000, dil kodu, mode_preference Choice, selected_text ≤20000).
/// </summary>
public sealed class AcceptAgentRunCommandValidator : AbstractValidator<AcceptAgentRunCommandRequest>
{
    private static readonly string[] ModePreferences = ["auto", "fast", "analysis", "deep_research"];

    public AcceptAgentRunCommandValidator()
    {
        RuleFor(x => x.Question)
            .NotEmpty()
            .MaximumLength(8000);

        RuleFor(x => x.Language)
            .NotEmpty()
            .Must(AgentContractFormats.IsValidLanguageCode)
            .WithMessage("Geçerli bir dil kodu bekleniyor (örn. tr, en).");

        RuleFor(x => x.ModePreference)
            .NotEmpty()
            .Must(m => ModePreferences.Contains(m))
            .WithMessage("mode_preference auto, fast, analysis veya deep_research olmalıdır.");

        RuleFor(x => x.BudgetProfile)
            .NotEmpty()
            .MaximumLength(128);

        RuleFor(x => x.SelectedText)
            .MaximumLength(20000);

        RuleFor(x => x.IdempotencyKey)
            .NotEmpty()
            .MaximumLength(128);

        RuleFor(x => x.GuestSessionId)
            .MaximumLength(128);
    }
}
