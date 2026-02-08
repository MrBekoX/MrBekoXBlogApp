using BlogApp.Server.Application.Features.PostFeature.Commands.SaveDraftCommand;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using FluentValidation;

namespace BlogApp.Server.Application.Features.PostFeature.Validators;

/// <summary>
/// Validator for SaveDraftCommandRequest - BUG-007 FIX
/// Ensures draft data is validated before saving to prevent invalid data entry.
/// </summary>
public class SaveDraftCommandRequestValidator : AbstractValidator<SaveDraftCommandRequest>
{
    public SaveDraftCommandRequestValidator()
    {
        RuleFor(x => x.SaveDraftCommandRequestDto)
            .NotNull().WithMessage(PostValidationMessages.DraftDataRequired);

        When(x => x.SaveDraftCommandRequestDto != null, () =>
        {
            // Draft için daha esnek kurallar - ama yine de validation gerekli
            RuleFor(x => x.SaveDraftCommandRequestDto!.Title)
                .NotEmpty().WithMessage(PostValidationMessages.TitleRequired)
                .MinimumLength(1).WithMessage(PostValidationMessages.TitleMinLength)
                .MaximumLength(200).WithMessage(PostValidationMessages.TitleMaxLength);

            RuleFor(x => x.SaveDraftCommandRequestDto!.Content)
                .NotEmpty().WithMessage(PostValidationMessages.ContentRequired)
                .MinimumLength(1).WithMessage(PostValidationMessages.ContentMinLength)
                .MaximumLength(500000).WithMessage(PostValidationMessages.ContentMaxLength);

            RuleFor(x => x.SaveDraftCommandRequestDto!.Excerpt)
                .MaximumLength(500).WithMessage(PostValidationMessages.ExcerptMaxLength)
                .When(x => !string.IsNullOrEmpty(x.SaveDraftCommandRequestDto!.Excerpt));

            RuleFor(x => x.SaveDraftCommandRequestDto!.MetaTitle)
                .MaximumLength(70).WithMessage(PostValidationMessages.MetaTitleMaxLength)
                .When(x => !string.IsNullOrEmpty(x.SaveDraftCommandRequestDto!.MetaTitle));

            RuleFor(x => x.SaveDraftCommandRequestDto!.MetaDescription)
                .MaximumLength(160).WithMessage(PostValidationMessages.MetaDescriptionMaxLength)
                .When(x => !string.IsNullOrEmpty(x.SaveDraftCommandRequestDto!.MetaDescription));

            RuleFor(x => x.SaveDraftCommandRequestDto!.FeaturedImageUrl)
                .Must(BeAValidAndSafeUrl).WithMessage(PostValidationMessages.FeaturedImageUrlInvalid)
                .When(x => !string.IsNullOrEmpty(x.SaveDraftCommandRequestDto!.FeaturedImageUrl));

            // Tag validasyonu
            RuleForEach(x => x.SaveDraftCommandRequestDto!.TagNames)
                .MaximumLength(50).WithMessage(PostValidationMessages.TagNameMaxLength)
                .Matches(@"^[^<>""'&]+$").WithMessage(PostValidationMessages.TagNameInvalid)
                .When(x => x.SaveDraftCommandRequestDto!.TagNames != null && x.SaveDraftCommandRequestDto!.TagNames.Any());
        });
    }

    /// <summary>
    /// URL'in geçerli ve güvenli olup olmadığını kontrol eder.
    /// SSRF saldırılarını önlemek için internal IP'lere erişimi engeller.
    /// </summary>
    private static bool BeAValidAndSafeUrl(string? url)
    {
        if (string.IsNullOrEmpty(url))
            return true;

        // Relative URL'lere izin ver (/uploads/... gibi)
        if (url.StartsWith('/'))
            return true;

        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri))
            return false;

        // Sadece HTTP/HTTPS'e izin ver
        if (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps)
            return false;

        // SSRF Prevention: Internal IP adreslerini engelle
        var host = uri.Host.ToLowerInvariant();

        // Localhost engelle
        if (host == "localhost" || host == "127.0.0.1" || host == "::1" || host == "[::1]")
            return false;

        // Private IP ranges engelle (RFC 1918)
        if (host.StartsWith("192.168.") || host.StartsWith("10.") || host.StartsWith("172.16.") ||
            host.StartsWith("172.17.") || host.StartsWith("172.18.") || host.StartsWith("172.19.") ||
            host.StartsWith("172.20.") || host.StartsWith("172.21.") || host.StartsWith("172.22.") ||
            host.StartsWith("172.23.") || host.StartsWith("172.24.") || host.StartsWith("172.25.") ||
            host.StartsWith("172.26.") || host.StartsWith("172.27.") || host.StartsWith("172.28.") ||
            host.StartsWith("172.29.") || host.StartsWith("172.30.") || host.StartsWith("172.31."))
            return false;

        // Link-local addresses engelle
        if (host.StartsWith("169.254."))
            return false;

        // Metadata endpoints engelle (cloud providers)
        if (host == "169.254.169.254" || host == "metadata.google.internal")
            return false;

        return true;
    }
}
