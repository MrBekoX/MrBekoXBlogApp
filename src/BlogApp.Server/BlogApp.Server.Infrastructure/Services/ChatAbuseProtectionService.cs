using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Serialization;
using BlogApp.Server.Application.Common.Interfaces.Services;
using BlogApp.Server.Application.Common.Options;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using StackExchange.Redis;

namespace BlogApp.Server.Infrastructure.Services;

public sealed class ChatAbuseProtectionService : IChatAbuseProtectionService
{
    private const string QuotaNamespace = "chat:quota";
    private const string EnforceQuotaScript = """
        local currentMinute = tonumber(redis.call('GET', KEYS[1]) or '0')
        local currentHour = tonumber(redis.call('GET', KEYS[2]) or '0')
        local currentDay = tonumber(redis.call('GET', KEYS[3]) or '0')
        local hasBypass = redis.call('GET', KEYS[4]) == '1'

        local nextMinute = currentMinute + 1
        local nextHour = currentHour + 1
        local nextDay = currentDay + tonumber(ARGV[7])

        if nextMinute > tonumber(ARGV[1]) or nextHour > tonumber(ARGV[2]) or nextDay > tonumber(ARGV[3]) then
            return 0
        end

        local requiresTurnstile = (not hasBypass) and (
            nextMinute > tonumber(ARGV[4]) or
            nextHour > tonumber(ARGV[5]) or
            nextDay > tonumber(ARGV[6])
        )

        if requiresTurnstile and tonumber(ARGV[12]) ~= 1 then
            return 2
        end

        if tonumber(ARGV[13]) == 1 then
            redis.call('SET', KEYS[4], '1', 'EX', tonumber(ARGV[11]))
        end

        local minuteValue = redis.call('INCRBY', KEYS[1], 1)
        if minuteValue == 1 then
            redis.call('EXPIRE', KEYS[1], tonumber(ARGV[8]))
        end

        local hourValue = redis.call('INCRBY', KEYS[2], 1)
        if hourValue == 1 then
            redis.call('EXPIRE', KEYS[2], tonumber(ARGV[9]))
        end

        local dayValue = redis.call('INCRBY', KEYS[3], tonumber(ARGV[7]))
        if dayValue == tonumber(ARGV[7]) then
            redis.call('EXPIRE', KEYS[3], tonumber(ARGV[10]))
        end

        return 1
        """;

    private readonly IConnectionMultiplexer? _redis;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ChatAbuseProtectionSettings _settings;
    private readonly TurnstileSettings _turnstileSettings;
    private readonly IHostEnvironment _hostEnvironment;
    private readonly ILogger<ChatAbuseProtectionService> _logger;

    public ChatAbuseProtectionService(
        IConnectionMultiplexer? redis,
        IHttpClientFactory httpClientFactory,
        IOptions<ChatAbuseProtectionSettings> settings,
        IOptions<TurnstileSettings> turnstileSettings,
        IHostEnvironment hostEnvironment,
        ILogger<ChatAbuseProtectionService> logger)
    {
        _redis = redis;
        _httpClientFactory = httpClientFactory;
        _settings = settings.Value;
        _turnstileSettings = turnstileSettings.Value;
        _hostEnvironment = hostEnvironment;
        _logger = logger;
    }

    public async Task<ChatAbuseDecision> AuthorizeAnonymousAsync(AnonymousChatRequest request, CancellationToken cancellationToken = default)
    {
        if (!_settings.Enabled)
        {
            return ChatAbuseDecision.Allow();
        }

        if (_redis?.IsConnected != true)
        {
            _logger.LogWarning("Anonymous chat rejected because Redis quota backend is unavailable.");
            return ChatAbuseDecision.Unavailable("Anonymous chat is temporarily unavailable.");
        }

        try
        {
            var db = _redis.GetDatabase();
            var remoteIp = NormalizeIp(request.RemoteIpAddress);
            var fingerprint = NormalizeFingerprint(request.ClientFingerprint);
            var scopeKey = BuildScopeKey(request.PostId, request.SessionId, remoteIp, fingerprint);
            var bypassKey = $"{QuotaNamespace}:turnstile:bypass:{scopeKey}";
            var estimatedTokens = EstimateTokens(request.Message, request.ConversationHistoryCount);
            var now = DateTimeOffset.UtcNow;

            var minuteKey = $"{QuotaNamespace}:req:minute:{scopeKey}:{now:yyyyMMddHHmm}";
            var hourKey = $"{QuotaNamespace}:req:hour:{scopeKey}:{now:yyyyMMddHH}";
            var dayKey = $"{QuotaNamespace}:tokens:day:{scopeKey}:{now:yyyyMMdd}";

            var quotaDecision = await EvaluateQuotaAsync(
                db,
                minuteKey,
                hourKey,
                dayKey,
                bypassKey,
                estimatedTokens,
                allowSoftExceed: false,
                grantBypass: false).ConfigureAwait(false);

            if (quotaDecision == QuotaEvaluationOutcome.Deny)
            {
                return ChatAbuseDecision.Deny("Anonymous chat quota exceeded. Please try again later.");
            }

            if (quotaDecision == QuotaEvaluationOutcome.Challenge)
            {
                var turnstileConfigured = !string.IsNullOrWhiteSpace(_turnstileSettings.SiteKey) &&
                                         !string.IsNullOrWhiteSpace(_turnstileSettings.SecretKey);

                if (!turnstileConfigured)
                {
                    if (_hostEnvironment.IsDevelopment() && _settings.AllowMissingTurnstileInDevelopment)
                    {
                        _logger.LogWarning("Anonymous chat soft quota exceeded but Turnstile is not configured; allowing request because development bypass is enabled.");
                        quotaDecision = await EvaluateQuotaAsync(
                            db,
                            minuteKey,
                            hourKey,
                            dayKey,
                            bypassKey,
                            estimatedTokens,
                            allowSoftExceed: true,
                            grantBypass: false).ConfigureAwait(false);
                    }
                    else
                    {
                        _logger.LogWarning("Anonymous chat rejected because Turnstile is not configured.");
                        return ChatAbuseDecision.Unavailable("Human verification is temporarily unavailable.");
                    }
                }
                else
                {
                    if (string.IsNullOrWhiteSpace(request.TurnstileToken))
                    {
                        return ChatAbuseDecision.Challenge("Turnstile verification required.");
                    }

                    var verified = await VerifyTurnstileAsync(request.TurnstileToken, remoteIp, cancellationToken).ConfigureAwait(false);
                    if (!verified)
                    {
                        return ChatAbuseDecision.Challenge("Turnstile verification failed.");
                    }

                    quotaDecision = await EvaluateQuotaAsync(
                        db,
                        minuteKey,
                        hourKey,
                        dayKey,
                        bypassKey,
                        estimatedTokens,
                        allowSoftExceed: true,
                        grantBypass: true).ConfigureAwait(false);
                }
            }

            if (quotaDecision == QuotaEvaluationOutcome.Deny)
            {
                return ChatAbuseDecision.Deny("Anonymous chat quota exceeded. Please try again later.");
            }

            if (quotaDecision == QuotaEvaluationOutcome.Challenge)
            {
                return ChatAbuseDecision.Challenge("Turnstile verification required.");
            }

            return ChatAbuseDecision.Allow();
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Anonymous chat rejected because quota enforcement failed.");
            return ChatAbuseDecision.Unavailable("Anonymous chat is temporarily unavailable.");
        }
    }

    private async Task<bool> VerifyTurnstileAsync(string token, string remoteIp, CancellationToken cancellationToken)
    {
        try
        {
            using var client = _httpClientFactory.CreateClient(nameof(ChatAbuseProtectionService));
            using var request = new HttpRequestMessage(HttpMethod.Post, _turnstileSettings.VerifyUrl)
            {
                Content = new FormUrlEncodedContent(new Dictionary<string, string>
                {
                    ["secret"] = _turnstileSettings.SecretKey,
                    ["response"] = token,
                    ["remoteip"] = remoteIp
                })
            };

            using var response = await client.SendAsync(request, cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                _logger.LogWarning("Turnstile verification failed with status code {StatusCode}", response.StatusCode);
                return false;
            }

            var payload = await response.Content.ReadFromJsonAsync<TurnstileVerificationResponse>(cancellationToken: cancellationToken).ConfigureAwait(false);
            if (payload is null || !payload.Success)
            {
                _logger.LogWarning("Turnstile rejected anonymous chat request. Errors: {Errors}", payload?.ErrorCodes is null ? "n/a" : string.Join(',', payload.ErrorCodes));
                return false;
            }

            if (!string.IsNullOrWhiteSpace(_settings.TurnstileAction) &&
                !string.IsNullOrWhiteSpace(payload.Action) &&
                !string.Equals(payload.Action, _settings.TurnstileAction, StringComparison.Ordinal))
            {
                _logger.LogWarning("Turnstile action mismatch. Expected {ExpectedAction}, got {ActualAction}", _settings.TurnstileAction, payload.Action);
                return false;
            }

            return true;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Turnstile verification request failed.");
            throw;
        }
    }

    private async Task<QuotaEvaluationOutcome> EvaluateQuotaAsync(
        IDatabase db,
        string minuteKey,
        string hourKey,
        string dayKey,
        string bypassKey,
        int estimatedTokens,
        bool allowSoftExceed,
        bool grantBypass)
    {
        var result = await db.ScriptEvaluateAsync(
            EnforceQuotaScript,
            [minuteKey, hourKey, dayKey, bypassKey],
            [
                _settings.HardRequestsPerMinute,
                _settings.HardRequestsPerHour,
                _settings.HardEstimatedTokensPerDay,
                _settings.SoftRequestsPerMinute,
                _settings.SoftRequestsPerHour,
                _settings.SoftEstimatedTokensPerDay,
                estimatedTokens,
                (int)TimeSpan.FromMinutes(2).TotalSeconds,
                (int)TimeSpan.FromHours(2).TotalSeconds,
                (int)TimeSpan.FromDays(2).TotalSeconds,
                (int)TimeSpan.FromMinutes(Math.Max(1, _settings.TurnstileBypassMinutes)).TotalSeconds,
                allowSoftExceed ? 1 : 0,
                grantBypass ? 1 : 0
            ]).ConfigureAwait(false);

        if (!int.TryParse(result.ToString(), out var parsed) ||
            !Enum.IsDefined(typeof(QuotaEvaluationOutcome), parsed))
        {
            throw new InvalidOperationException("Redis quota script returned an unexpected result.");
        }

        return (QuotaEvaluationOutcome)parsed;
    }

    private static string NormalizeIp(string? ipAddress) =>
        string.IsNullOrWhiteSpace(ipAddress) ? "unknown" : ipAddress.Trim();

    private static string NormalizeFingerprint(string? fingerprint) =>
        string.IsNullOrWhiteSpace(fingerprint) ? "missing" : fingerprint.Trim();

    private static int EstimateTokens(string message, int historyCount)
    {
        var length = string.IsNullOrWhiteSpace(message) ? 0 : message.Trim().Length;
        var estimated = (length * 4) + 192 + (Math.Max(0, historyCount) * 96);
        return Math.Clamp(estimated, 256, 8192);
    }

    private static string BuildScopeKey(Guid postId, string sessionId, string remoteIp, string fingerprint)
    {
        var raw = $"{postId:D}|{sessionId}|{remoteIp}|{fingerprint}";
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(raw));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }

    private sealed class TurnstileVerificationResponse
    {
        [JsonPropertyName("success")]
        public bool Success { get; init; }

        [JsonPropertyName("action")]
        public string? Action { get; init; }

        [JsonPropertyName("error-codes")]
        public string[]? ErrorCodes { get; init; }
    }

    private enum QuotaEvaluationOutcome
    {
        Deny = 0,
        Allow = 1,
        Challenge = 2
    }
}
