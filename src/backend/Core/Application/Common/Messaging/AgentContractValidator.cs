using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using BlogApp.Core.Application.Common.Options;

namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>Bir sözleşme ihlali sonucu; IsValid false iken Error doludur.</summary>
public sealed record AgentContractValidationResult(
    bool IsValid,
    AgentContractError? Error,
    AgentEnvelope? Envelope,
    JsonObject? PayloadNode)
{
    public static AgentContractValidationResult Fail(AgentContractError error) => new(false, error, null, null);

    public static AgentContractValidationResult Ok(AgentEnvelope envelope, JsonObject payloadNode) =>
        new(true, null, envelope, payloadNode);
}

/// <summary>
/// B1 sözleşme doğrulayıcı: gövdeyi JSON olarak çözümler ve kontrollü kategorilerle reddeder —
/// eksik alan, bilinmeyen sürüm, aşırı boyut, hatalı tür, biçim, fazladan alan ve yön/üretici uyuşmazlığı
/// (plan kabul ölçütü, satır 241). Python transport katmanındaki parse_envelope ile aynı adım sırasını
/// uygular; ortak fixture seti iki tarafın denkliğini sabitler.
/// </summary>
public sealed class AgentContractValidator
{
    private static readonly IReadOnlyList<AgentFieldRule> EnvelopeFields =
    [
        AgentFieldRule.Text("message_id", required: true, format: AgentFieldFormat.Uuid),
        AgentFieldRule.Text("message_type", required: true, maxLength: 64),
        AgentFieldRule.Integer("schema_version", required: true, minimum: 0),
        AgentFieldRule.Text("run_id", format: AgentFieldFormat.Uuid),
        AgentFieldRule.Text("conversation_id", format: AgentFieldFormat.Uuid),
        AgentFieldRule.Text("correlation_id", required: true, format: AgentFieldFormat.Uuid),
        AgentFieldRule.Text("causation_id", format: AgentFieldFormat.Uuid),
        AgentFieldRule.Text("occurred_at", required: true, format: AgentFieldFormat.UtcIso),
        AgentFieldRule.Text("deadline_at", format: AgentFieldFormat.UtcIso),
        AgentFieldRule.Choice("producer", required: true, AgentMessageTypeRegistry.AllProducers.ToArray()),
        AgentFieldRule.Text("trace_context", format: AgentFieldFormat.TraceParent),
        AgentFieldRule.Integer("delivery_attempt", minimum: 0),
        AgentFieldRule.Text("payload", required: true) with { Kind = AgentFieldKind.Object }
    ];

    private static readonly JsonSerializerOptions PayloadJsonOptions = new()
    {
        NumberHandling = System.Text.Json.Serialization.JsonNumberHandling.Strict
    };

    private readonly AgentMessagingSettings _settings;

    public AgentContractValidator(AgentMessagingSettings? settings = null)
    {
        _settings = settings ?? new AgentMessagingSettings();
    }

    /// <summary>Doğrulayıcı tarafından uygulanan zarf alan kümesi; şema aynası testleri kullanır.</summary>
    public static IReadOnlyList<AgentFieldRule> EnvelopeFieldRules => EnvelopeFields;

    public AgentContractValidationResult Validate(string json) =>
        ValidateCore(Encoding.UTF8.GetByteCount(json), () => JsonNode.Parse(json));

    public AgentContractValidationResult Validate(byte[] utf8Payload) =>
        ValidateCore(utf8Payload.Length, () => JsonNode.Parse(utf8Payload));

    /// <summary>Doğrular ve payload'ı tür bazlı DTO'ya çözer; DTO bilinmeyen alan taşıyamaz.</summary>
    public bool TryValidateAs<TPayload>(string json,
        [System.Diagnostics.CodeAnalysis.NotNullWhen(true)] out AgentEnvelope? envelope,
        [System.Diagnostics.CodeAnalysis.NotNullWhen(true)] out TPayload? payload,
        [System.Diagnostics.CodeAnalysis.NotNullWhen(false)] out AgentContractError? error)
        where TPayload : AgentPayloadBase
    {
        var result = Validate(json);
        if (!result.IsValid)
        {
            envelope = null;
            payload = null;
            error = result.Error!;
            return false;
        }

        if (!AgentMessageTypeRegistry.TryGet(result.Envelope!.MessageType, out var spec)
            || spec.PayloadDtoType != typeof(TPayload))
        {
            envelope = null;
            payload = null;
            error = new AgentContractError(
                AgentContractErrorCategory.WrongType,
                "payload",
                $"payload DTO türü mesaj türüyle uyuşmuyor: {typeof(TPayload).Name}");
            return false;
        }

        TPayload? typed;
        try
        {
            typed = result.PayloadNode!.Deserialize<TPayload>(PayloadJsonOptions);
        }
        catch (JsonException)
        {
            envelope = null;
            payload = null;
            error = new AgentContractError(AgentContractErrorCategory.WrongType, "payload", "payload DTO çözümlemesi başarısız");
            return false;
        }

        if (typed is null)
        {
            envelope = null;
            payload = null;
            error = new AgentContractError(AgentContractErrorCategory.WrongType, "payload", "payload boş çözümlendi");
            return false;
        }

        if (typed.ExtensionData is { Count: > 0 })
        {
            envelope = null;
            payload = null;
            error = new AgentContractError(
                AgentContractErrorCategory.ExtraField,
                typed.ExtensionData.Keys.First(),
                $"bilinmeyen payload alanı: {typed.ExtensionData.Keys.First()}");
            return false;
        }

        envelope = result.Envelope;
        payload = typed;
        error = null;
        return true;
    }

    private AgentContractValidationResult ValidateCore(int byteCount, Func<JsonNode?> parse)
    {
        if (byteCount > _settings.MaxPayloadBytes)
        {
            return AgentContractValidationResult.Fail(new AgentContractError(
                AgentContractErrorCategory.Oversized,
                "payload",
                $"gövde {_settings.MaxPayloadBytes} bayt üst sınırını aşıyor: {byteCount} bayt"));
        }

        JsonNode? root;
        try
        {
            root = parse();
        }
        catch (JsonException)
        {
            return AgentContractValidationResult.Fail(new AgentContractError(
                AgentContractErrorCategory.BadFormat, "body", "gövde geçerli JSON değil"));
        }

        if (root is not JsonObject envelopeObject)
        {
            return AgentContractValidationResult.Fail(new AgentContractError(
                AgentContractErrorCategory.WrongType, "body", "zarf bir JSON nesnesi olmalıdır"));
        }

        var envelopeError = ValidateFields(envelopeObject, EnvelopeFields, string.Empty);
        if (envelopeError is not null)
        {
            return AgentContractValidationResult.Fail(envelopeError);
        }

        if (envelopeObject["schema_version"]!.GetValue<int>() != AgentMessageTypeRegistry.SchemaVersion)
        {
            return AgentContractValidationResult.Fail(new AgentContractError(
                AgentContractErrorCategory.UnknownVersion,
                "schema_version",
                $"bilinmeyen sözleşme sürümü: {envelopeObject["schema_version"]!.GetValue<int>()}"));
        }

        var messageType = envelopeObject["message_type"]!.GetValue<string>();
        if (!AgentMessageTypeRegistry.TryGet(messageType, out var spec))
        {
            return AgentContractValidationResult.Fail(new AgentContractError(
                AgentContractErrorCategory.UnknownType, "message_type", $"bilinmeyen mesaj türü: {messageType}"));
        }

        var runId = envelopeObject["run_id"]?.GetValue<string>();
        var conversationId = envelopeObject["conversation_id"]?.GetValue<string>();
        if (spec.RequiresRunIdentity && (runId is null || conversationId is null))
        {
            return AgentContractValidationResult.Fail(new AgentContractError(
                AgentContractErrorCategory.MissingField,
                "run_id",
                $"{messageType} için run_id ve conversation_id zorunludur"));
        }

        if (!spec.RequiresRunIdentity && (runId is not null || conversationId is not null))
        {
            return AgentContractValidationResult.Fail(new AgentContractError(
                AgentContractErrorCategory.WrongType,
                "run_id",
                $"{messageType} run kimliği taşımaz"));
        }

        if (spec.RequiresDeadline && envelopeObject["deadline_at"] is null)
        {
            return AgentContractValidationResult.Fail(new AgentContractError(
                AgentContractErrorCategory.MissingField, "deadline_at", $"{messageType} için deadline_at zorunludur"));
        }

        if (!spec.AllowedProducers.Contains(envelopeObject["producer"]!.GetValue<string>()))
        {
            return AgentContractValidationResult.Fail(new AgentContractError(
                AgentContractErrorCategory.ProducerMismatch,
                "producer",
                $"{messageType} yönü için üretici izinli değil: {envelopeObject["producer"]!.GetValue<string>()}"));
        }

        if (envelopeObject["payload"] is not JsonObject payloadObject)
        {
            return AgentContractValidationResult.Fail(new AgentContractError(
                AgentContractErrorCategory.WrongType, "payload", "payload bir JSON nesnesi olmalıdır"));
        }

        var payloadError = ValidateFields(payloadObject, spec.PayloadFields, "payload.");
        if (payloadError is not null)
        {
            return AgentContractValidationResult.Fail(payloadError);
        }

        var envelope = new AgentEnvelope
        {
            MessageId = envelopeObject["message_id"]!.GetValue<string>(),
            MessageType = messageType,
            SchemaVersion = envelopeObject["schema_version"]!.GetValue<int>(),
            RunId = runId,
            ConversationId = conversationId,
            CorrelationId = envelopeObject["correlation_id"]!.GetValue<string>(),
            CausationId = envelopeObject["causation_id"]?.GetValue<string>(),
            OccurredAt = envelopeObject["occurred_at"]!.GetValue<string>(),
            DeadlineAt = envelopeObject["deadline_at"]?.GetValue<string>(),
            Producer = envelopeObject["producer"]!.GetValue<string>(),
            TraceContext = envelopeObject["trace_context"]?.GetValue<string>(),
            DeliveryAttempt = envelopeObject["delivery_attempt"]?.GetValue<int>() ?? 0,
            Payload = JsonSerializer.SerializeToElement(payloadObject, PayloadJsonOptions)
        };

        var crossError = ValidateCrossRules(envelope, payloadObject);
        if (crossError is not null)
        {
            return AgentContractValidationResult.Fail(crossError);
        }

        return AgentContractValidationResult.Ok(envelope, payloadObject);
    }

    private static AgentContractError? ValidateFields(JsonObject obj, IReadOnlyList<AgentFieldRule> fields, string pathPrefix)
    {
        // 1) Açık null taşıma yasak (sözleşme: alan çıkarılır).
        foreach (var key in obj.Select(kv => kv.Key))
        {
            if (!fields.Any(f => f.Name == key))
            {
                return new AgentContractError(
                    AgentContractErrorCategory.ExtraField, pathPrefix + key, $"bilinmeyen alan: {pathPrefix + key}");
            }

            if (obj[key] is null)
            {
                return new AgentContractError(
                    AgentContractErrorCategory.WrongType, pathPrefix + key, "null taşınmaz; alan çıkarılmalıdır");
            }
        }

        // 2) Zorunlu alanlar kural sırasına göre.
        foreach (var field in fields)
        {
            if (field.Required && obj[field.Name] is null)
            {
                return new AgentContractError(
                    AgentContractErrorCategory.MissingField, pathPrefix + field.Name, $"zorunlu alan eksik: {field.Name}");
            }
        }

        // 3) Sunulan alanların tür/biçim kuralları kural sırasına göre.
        foreach (var field in fields)
        {
            var node = obj[field.Name];
            if (node is null)
            {
                continue;
            }

            var error = ValidateValue(field, node, pathPrefix + field.Name);
            if (error is not null)
            {
                return error;
            }
        }

        return null;
    }

    private static AgentContractError? ValidateValue(AgentFieldRule field, JsonNode node, string path)
    {
        switch (field.Kind)
        {
            case AgentFieldKind.String:
                if (node.GetValueKind() != JsonValueKind.String)
                {
                    return WrongType(path, "dize bekleniyor");
                }

                var text = node.GetValue<string>();
                if (field.EnumValues is not null && !field.EnumValues.Contains(text))
                {
                    return WrongType(path, $"izinli değerler: {string.Join(", ", field.EnumValues)}");
                }

                if (field.MinLength is not null && text.Length < field.MinLength)
                {
                    return WrongType(path, $"en az {field.MinLength} karakter bekleniyor");
                }

                if (field.MaxLength is not null && text.Length > field.MaxLength)
                {
                    return WrongType(path, $"en çok {field.MaxLength} karakter bekleniyor");
                }

                return field.Format switch
                {
                    AgentFieldFormat.Uuid when !AgentContractFormats.IsValidUuid(text) =>
                        BadFormat(path, "kanonik UUID bekleniyor"),
                    AgentFieldFormat.UtcIso when !AgentContractFormats.IsValidUtcIso(text) =>
                        BadFormat(path, "UTC ISO 8601 ('Z' sonekli) bekleniyor"),
                    AgentFieldFormat.HashHex when !AgentContractFormats.IsValidHashHex(text) =>
                        BadFormat(path, "64 haneli küçük harf SHA-256 hex bekleniyor"),
                    AgentFieldFormat.LanguageCode when !AgentContractFormats.IsValidLanguageCode(text) =>
                        BadFormat(path, "geçersiz dil kodu"),
                    AgentFieldFormat.TraceParent when !AgentContractFormats.IsValidTraceParent(text) =>
                        BadFormat(path, "W3C traceparent bekleniyor"),
                    _ => null
                };

            case AgentFieldKind.Integer:
                if (node.GetValueKind() != JsonValueKind.Number
                    || node is not JsonValue intValueNode
                    || !intValueNode.TryGetValue<long>(out var intValue))
                {
                    return WrongType(path, "tamsayı bekleniyor");
                }

                return field.Minimum is not null && intValue < field.Minimum
                    ? WrongType(path, $"değer {field.Minimum} değerinden küçük olamaz")
                    : null;

            case AgentFieldKind.Number:
                if (node.GetValueKind() != JsonValueKind.Number
                    || node is not JsonValue numberNode
                    || !numberNode.TryGetValue<double>(out var numberValue))
                {
                    return WrongType(path, "sayı bekleniyor");
                }

                return field.Minimum is not null && numberValue < field.Minimum
                    ? WrongType(path, $"değer {field.Minimum} değerinden küçük olamaz")
                    : null;

            case AgentFieldKind.Boolean:
                return node.GetValueKind() is JsonValueKind.True or JsonValueKind.False
                    ? null
                    : WrongType(path, "boolean bekleniyor");

            case AgentFieldKind.Array:
                if (node.GetValueKind() != JsonValueKind.Array)
                {
                    return WrongType(path, "dizi bekleniyor");
                }

                var array = node.AsArray();
                if (field.MinItems is not null && array.Count < field.MinItems)
                {
                    return WrongType(path, $"en az {field.MinItems} öğe bekleniyor");
                }

                if (field.Items is null)
                {
                    return null;
                }

                foreach (var item in array)
                {
                    if (item is null)
                    {
                        return WrongType(path, "dizi öğesi null olamaz");
                    }

                    var itemError = ValidateValue(field.Items, item, path + "[]");
                    if (itemError is not null)
                    {
                        return itemError;
                    }
                }

                return null;

            case AgentFieldKind.Object:
                if (node.GetValueKind() != JsonValueKind.Object)
                {
                    return WrongType(path, "nesne bekleniyor");
                }

                if (field.ObjectFields is not null)
                {
                    return ValidateFields(node.AsObject(), field.ObjectFields, path + ".");
                }

                if (field.MapValueKind is not null)
                {
                    foreach (var (key, value) in node.AsObject())
                    {
                        if (value is null)
                        {
                            return WrongType(path + "." + key, "null taşınmaz; alan çıkarılmalıdır");
                        }

                        var expected = field.MapValueKind.Value;
                        var valid = expected switch
                        {
                            AgentFieldKind.String => value.GetValueKind() == JsonValueKind.String,
                            AgentFieldKind.Integer => value.GetValueKind() == JsonValueKind.Number
                                && value is JsonValue mapIntValue && mapIntValue.TryGetValue<long>(out _),
                            AgentFieldKind.Number => value.GetValueKind() == JsonValueKind.Number,
                            AgentFieldKind.Boolean => value.GetValueKind() is JsonValueKind.True or JsonValueKind.False,
                            _ => false
                        };
                        if (!valid)
                        {
                            return WrongType(path + "." + key, $"değer türü {expected} olmalıdır");
                        }
                    }
                }

                return null;

            default:
                return WrongType(path, "desteklenmeyen alan türü");
        }
    }

    private static AgentContractError? ValidateCrossRules(AgentEnvelope envelope, JsonObject payload)
    {
        switch (envelope.MessageType)
        {
            case AgentMessageTypes.ExecutionRequested:
                var any = payload.ContainsKey("article_id") || payload.ContainsKey("article_revision") || payload.ContainsKey("article_content_hash");
                var all = payload.ContainsKey("article_id") && payload.ContainsKey("article_revision") && payload.ContainsKey("article_content_hash");
                return any && !all
                    ? WrongType("payload.article_id", "makale referansı üç alanın tamamını gerektirir")
                    : null;

            case AgentMessageTypes.ActionResult:
                return payload["outcome"]!.GetValue<string>() == "accepted" && payload["applied_article_revision"] is null
                    ? Missing("payload.applied_article_revision", "kabul edilen eylem için applied_article_revision zorunludur")
                    : null;

            case AgentMessageTypes.RunModeSelected:
                return payload["requires_web_search"]!.GetValue<bool>()
                    && payload["selected_mode"]!.GetValue<string>() != "deep_research"
                    ? WrongType("payload.selected_mode", "requires_web_search yalnız deep_research modunda true olabilir")
                    : null;

            case AgentMessageTypes.RunCompleted:
            case AgentMessageTypes.RunPartiallyCompleted:
                var hasAnswer = payload.ContainsKey("answer");
                var hasReport = payload.ContainsKey("report");
                if (!hasAnswer && !hasReport)
                {
                    return Missing("payload.answer", "answer veya report zorunludur");
                }

                if (hasAnswer && hasReport)
                {
                    return WrongType("payload.answer", "answer ve report aynı anda dolu olamaz");
                }

                var usageError = UsageRunIdMismatch(payload, envelope.RunId!);
                if (usageError is not null)
                {
                    return usageError;
                }

                if (payload["action_proposal"] is JsonObject proposal
                    && proposal["run_id"]!.GetValue<string>() != envelope.RunId)
                {
                    return WrongType("payload.action_proposal.run_id", "action_proposal.run_id zarf run_id ile uyuşmuyor");
                }

                return null;

            case AgentMessageTypes.RunNeedsInput:
            case AgentMessageTypes.RunFailed:
            case AgentMessageTypes.RunCancelled:
                return UsageRunIdMismatch(payload, envelope.RunId!);

            case AgentMessageTypes.ActionProposed:
                return payload["run_id"]!.GetValue<string>() != envelope.RunId
                    ? WrongType("payload.run_id", "payload.run_id zarf run_id ile uyuşmuyor")
                    : null;

            case AgentMessageTypes.ArticleContentChanged:
                var action = payload["action"]!.GetValue<string>();
                return action == "updated" && payload["content_hash"] is null
                    ? Missing("payload.content_hash", "updated eylemi için content_hash zorunludur")
                    : action == "unpublished" && payload.ContainsKey("content_hash")
                        ? WrongType("payload.content_hash", "unpublished eylemi content_hash taşımaz")
                        : null;

            case AgentMessageTypes.SyncBatch:
                return payload["batch_index"]!.GetValue<long>() >= payload["total_batches"]!.GetValue<long>()
                    ? WrongType("payload.batch_index", "batch_index, total_batches değerinden küçük olmalıdır")
                    : null;

            default:
                return null;
        }
    }

    private static AgentContractError? UsageRunIdMismatch(JsonObject payload, string runId)
    {
        if (payload["usage"] is not JsonObject usage)
        {
            return null;
        }

        return usage["run_id"]!.GetValue<string>() != runId
            ? WrongType("payload.usage.run_id", "usage.run_id zarf run_id ile uyuşmuyor")
            : null;
    }

    private static AgentContractError Missing(string field, string message) =>
        new(AgentContractErrorCategory.MissingField, field, message);

    private static AgentContractError WrongType(string field, string message) =>
        new(AgentContractErrorCategory.WrongType, field, message);

    private static AgentContractError BadFormat(string field, string message) =>
        new(AgentContractErrorCategory.BadFormat, field, message);
}
