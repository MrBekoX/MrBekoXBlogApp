using BlogApp.Server.Domain.Common;

namespace BlogApp.Server.Application.Common.Interfaces.Persistence;

/// <summary>
/// Combined Repository arayüzü
/// </summary>
public interface IRepository<T> where T : BaseEntity
{
}
