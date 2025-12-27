using BlogApp.Server.Domain.Common;

namespace BlogApp.Server.Application.Common.Interfaces;

/// <summary>
/// Combined Repository arayüzü
/// </summary>
public interface IRepository<T> : IReadRepository<T>, IWriteRepository<T> where T : BaseEntity
{
}