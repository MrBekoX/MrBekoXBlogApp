namespace BlogApp.Server.Domain.Exceptions;

/// <summary>
/// Domain katmanı için temel exception sınıfı
/// </summary>
public class DomainException : Exception
{
    public DomainException() : base() { }

    public DomainException(string message) : base(message) { }

    public DomainException(string message, Exception innerException) : base(message, innerException) { }
}

/// <summary>
/// Entity bulunamadığında fırlatılan exception
/// </summary>
public class NotFoundException : DomainException
{
    public NotFoundException() : base() { }

    public NotFoundException(string message) : base(message) { }

    public NotFoundException(string name, object key)
        : base($"Entity \"{name}\" ({key}) was not found.") { }
}

/// <summary>
/// Validasyon hatası için exception
/// </summary>
public class ValidationException : DomainException
{
    public IDictionary<string, string[]> Errors { get; }

    public ValidationException() : base("One or more validation failures have occurred.")
    {
        Errors = new Dictionary<string, string[]>();
    }

    public ValidationException(IDictionary<string, string[]> errors) : this()
    {
        Errors = errors;
    }

    public ValidationException(string propertyName, string error) : this()
    {
        Errors = new Dictionary<string, string[]>
        {
            { propertyName, new[] { error } }
        };
    }
}

/// <summary>
/// Yetkilendirme hatası için exception
/// </summary>
public class ForbiddenException : DomainException
{
    public ForbiddenException() : base("You do not have permission to access this resource.") { }

    public ForbiddenException(string message) : base(message) { }
}

/// <summary>
/// Çakışma durumları için exception
/// </summary>
public class ConflictException : DomainException
{
    public ConflictException() : base() { }

    public ConflictException(string message) : base(message) { }
}
