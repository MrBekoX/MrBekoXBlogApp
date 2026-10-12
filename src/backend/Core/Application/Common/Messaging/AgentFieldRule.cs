namespace BlogApp.Core.Application.Common.Messaging;

/// <summary>JSON değer türleri; JSON Schema türleriyle birebir eşlenir.</summary>
public enum AgentFieldKind
{
    String,
    Integer,
    Number,
    Boolean,
    Array,
    Object
}

/// <summary>Dize biçim kuralları; BadFormat kategorisini üreten alanlar.</summary>
public enum AgentFieldFormat
{
    None,
    Uuid,
    UtcIso,
    HashHex,
    LanguageCode,
    TraceParent
}

/// <summary>
/// Tek payload/envelope alanının doğrulama kuralı; JSON Schema properties+required+enum satırının
/// .NET yansımasıdır. Schema aynası testleri bu kuralları şema dosyalarıyla karşılaştırır.
/// </summary>
public sealed record AgentFieldRule
{
    public required string Name { get; init; }
    public AgentFieldKind Kind { get; init; } = AgentFieldKind.String;
    public bool Required { get; init; }
    public int? MinLength { get; init; }
    public int? MaxLength { get; init; }
    public long? Minimum { get; init; }
    public int? MinItems { get; init; }
    public IReadOnlyList<string>? EnumValues { get; init; }
    public AgentFieldFormat Format { get; init; } = AgentFieldFormat.None;
    public AgentFieldRule? Items { get; init; }

    /// <summary>Nesne türü alanın kapalı alan kümesi (additionalProperties: false).</summary>
    public IReadOnlyList<AgentFieldRule>? ObjectFields { get; init; }

    /// <summary>Açık nesne (map) için değer türü kısıtı; örn. detail: map&lt;string,string&gt;.</summary>
    public AgentFieldKind? MapValueKind { get; init; }

    public static AgentFieldRule Text(string name, bool required = false, int minLength = 1, int? maxLength = null,
        AgentFieldFormat format = AgentFieldFormat.None) => new()
    {
        Name = name,
        Required = required,
        MinLength = minLength,
        MaxLength = maxLength,
        Format = format
    };

    public static AgentFieldRule Choice(string name, bool required, params string[] values) => new()
    {
        Name = name,
        Required = required,
        EnumValues = values
    };

    public static AgentFieldRule Integer(string name, bool required = false, long minimum = 0) => new()
    {
        Name = name,
        Kind = AgentFieldKind.Integer,
        Required = required,
        Minimum = minimum
    };

    public static AgentFieldRule Decimal(string name, bool required = false, double minimum = 0) => new()
    {
        Name = name,
        Kind = AgentFieldKind.Number,
        Required = required,
        Minimum = (long)minimum
    };

    public static AgentFieldRule Flag(string name, bool required = false) => new()
    {
        Name = name,
        Kind = AgentFieldKind.Boolean,
        Required = required
    };

    public static AgentFieldRule List(string name, AgentFieldRule itemRule, bool required = false, int? minItems = null) => new()
    {
        Name = name,
        Kind = AgentFieldKind.Array,
        Required = required,
        Items = itemRule,
        MinItems = minItems
    };

    public static AgentFieldRule Map(string name, AgentFieldKind valueKind, bool required = false) => new()
    {
        Name = name,
        Kind = AgentFieldKind.Object,
        Required = required,
        MapValueKind = valueKind
    };

    public static AgentFieldRule Composite(string name, bool required, params AgentFieldRule[] fields) => new()
    {
        Name = name,
        Kind = AgentFieldKind.Object,
        Required = required,
        ObjectFields = fields
    };
}
