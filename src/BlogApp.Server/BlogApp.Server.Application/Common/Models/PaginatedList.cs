using System.Text.Json.Serialization;

namespace BlogApp.Server.Application.Common.Models;

/// <summary>
/// Sayfalanmış liste modeli
/// </summary>
public class PaginatedList<T>
{
    public List<T> Items { get; set; } = new();
    public int PageNumber { get; set; }
    public int PageSize { get; set; }
    public int TotalPages { get; set; }
    public int TotalCount { get; set; }

    public PaginatedList()
    {
    }

    [JsonConstructor]
    public PaginatedList(List<T> items, int pageNumber, int pageSize, int totalPages, int totalCount)
    {
        Items = items;
        PageNumber = pageNumber;
        PageSize = pageSize;
        TotalPages = totalPages;
        TotalCount = totalCount;
    }

    public PaginatedList(List<T> items, int count, int pageNumber, int pageSize)
    {
        PageNumber = pageNumber;
        PageSize = pageSize;
        TotalPages = (int)Math.Ceiling(count / (double)pageSize);
        TotalCount = count;
        Items = items;
    }

    public bool HasPreviousPage => PageNumber > 1;
    public bool HasNextPage => PageNumber < TotalPages;

    public static PaginatedList<T> Create(IEnumerable<T> source, int pageNumber, int pageSize)
    {
        var count = source.Count();
        var items = source.Skip((pageNumber - 1) * pageSize).Take(pageSize).ToList();
        return new PaginatedList<T>(items, count, pageNumber, pageSize);
    }

    public static PaginatedList<T> Empty(int pageNumber = 1, int pageSize = 10)
    {
        return new PaginatedList<T>(new List<T>(), 0, pageNumber, pageSize);
    }
}

