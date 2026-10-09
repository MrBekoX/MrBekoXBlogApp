using BlogApp.Core.Domain.Common;

namespace BlogApp.Core.Application.Common.Interfaces.Persistence;

/// <summary>
/// Combined Repository arayüzü
/// </summary>
public interface IRepository<T> where T : BaseEntity
{
}
