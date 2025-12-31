using BlogApp.Server.Application.Common.Models;

namespace BlogApp.Server.Application.Common.BusinessRuleEngine;

public class BusinessRuleEngine
{
    public static Result Run(params Result[] rules)
    {
        foreach (var rule in rules)
        {
            if (!rule.IsSuccess)
            {
                return rule;
            }
        }
        return Result.Success();
    }

    public static async Task<Result> RunAsync(params Func<Task<Result>>[] rules)
    {
        foreach (var rule in rules)
        {
            var result = await rule();
            if (!result.IsSuccess)
            {
                return result;
            }
        }
        return Result.Success();
    }
}

