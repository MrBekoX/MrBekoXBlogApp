using BlogApp.Core.Application.Common.Messaging;
using BlogApp.Core.Application.Features.AgentFeature.Services;
using FluentValidation;

namespace BlogApp.Core.Application.Features.AgentFeature.Commands.AcceptAgentRunCommand;

/// <summary>
/// Kabul komutunun giriş doğrulaması; kural kümesi B1 payload sözleşmesiyle aynıdır
/// (question ≤8000, dil kodu, mode_preference Choice, selected_text ≤20000) + K6 konu kuralları:
/// conversationTopic auto|who_am_i; who_am_i makale bağlamı/seçili metin taşımaz ve /research ile
/// kullanılamaz (açıklamalı validation_error).
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

        RuleFor(x => x.ConversationTopic)
            .Must(AgentConversationTopics.IsKnown)
            .WithMessage("conversationTopic auto veya who_am_i olmalıdır.");

        When(x => x.ConversationTopic == AgentConversationTopics.WhoAmI, () =>
        {
            RuleFor(x => x.ArticleId)
                .Null()
                .WithMessage(WhoAmIArticleMessage);

            RuleFor(x => x.SelectedText)
                .Empty()
                .WithMessage(WhoAmISelectedTextMessage);

            RuleFor(x => x.IsResearchRequest)
                .Equal(false)
                .WithMessage(WhoAmIResearchMessage);
        });
    }

    public const string WhoAmIArticleMessage =
        "Who am I konusu makale bağlamı taşıyamaz: yanıtlar yalnız blog sahibinin onaylı profilinden üretilir. articleId göndermeyin veya Otomatik konuyu seçin.";

    public const string WhoAmISelectedTextMessage =
        "Who am I konusu seçili metin taşıyamaz: seçili metin profil kaynağı değildir. selectedText göndermeyin veya Otomatik konuyu seçin.";

    public const string WhoAmIResearchMessage =
        "Who am I konusu web araştırması başlatamaz: /research yerine /messages uç noktasını kullanın.";
}
