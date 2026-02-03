using BlogApp.Server.Application.Features.PostFeature.Commands.CreatePostCommand;
using BlogApp.Server.Application.Features.PostFeature.Constants;
using FluentValidation;

namespace BlogApp.Server.Application.Features.PostFeature.Validators;

public class CreatePostCommandRequestValidator : AbstractValidator<CreatePostCommandRequest>
{
    public CreatePostCommandRequestValidator()
    {
        RuleFor(x => x.CreatePostCommandRequestDto)
            .NotNull().WithMessage("Request data is required");

        When(x => x.CreatePostCommandRequestDto != null, () =>
        {
            RuleFor(x => x.CreatePostCommandRequestDto!.Title)
                .NotEmpty().WithMessage(PostValidationMessages.TitleRequired)
                .MinimumLength(3).WithMessage(PostValidationMessages.TitleMinLength)
                .MaximumLength(200).WithMessage(PostValidationMessages.TitleMaxLength);

            RuleFor(x => x.CreatePostCommandRequestDto!.Content)
                .NotEmpty().WithMessage(PostValidationMessages.ContentRequired)
                .MinimumLength(10).WithMessage(PostValidationMessages.ContentMinLength)
                .MaximumLength(500000).WithMessage(PostValidationMessages.ContentMaxLength);

            RuleFor(x => x.CreatePostCommandRequestDto!.Excerpt)
                .MaximumLength(500).WithMessage(PostValidationMessages.ExcerptMaxLength)
                .When(x => !string.IsNullOrEmpty(x.CreatePostCommandRequestDto!.Excerpt));

            RuleFor(x => x.CreatePostCommandRequestDto!.MetaTitle)
                .MaximumLength(70).WithMessage(PostValidationMessages.MetaTitleMaxLength)
                .When(x => !string.IsNullOrEmpty(x.CreatePostCommandRequestDto!.MetaTitle));

            RuleFor(x => x.CreatePostCommandRequestDto!.MetaDescription)
                .MaximumLength(160).WithMessage(PostValidationMessages.MetaDescriptionMaxLength)
                .When(x => !string.IsNullOrEmpty(x.CreatePostCommandRequestDto!.MetaDescription));

            RuleFor(x => x.CreatePostCommandRequestDto!.FeaturedImageUrl)
                .Must(BeAValidAndSafeUrl).WithMessage(PostValidationMessages.FeaturedImageUrlInvalid)
                .When(x => !string.IsNullOrEmpty(x.CreatePostCommandRequestDto!.FeaturedImageUrl));

            // Tag validasyonu
            RuleForEach(x => x.CreatePostCommandRequestDto!.TagNames)
                .MaximumLength(50).WithMessage(PostValidationMessages.TagNameMaxLength)
                .Matches(@"^[^<>""'&]+$").WithMessage(PostValidationMessages.TagNameInvalid)
                .When(x => x.CreatePostCommandRequestDto!.TagNames != null && x.CreatePostCommandRequestDto!.TagNames.Any());
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

