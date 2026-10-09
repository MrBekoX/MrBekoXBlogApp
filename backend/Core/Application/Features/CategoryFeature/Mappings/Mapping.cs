using AutoMapper;
using BlogApp.Core.Application.Features.CategoryFeature.DTOs;
using BlogApp.Core.Domain.Entities;

namespace BlogApp.Core.Application.Features.CategoryFeature.Mappings;

public class Mapping : Profile
{
    public Mapping()
    {
        CreateMap<Category, CreateCategoryCommandDto>().ReverseMap();
        CreateMap<Category, UpdateCategoryCommandDto>().ReverseMap();
        CreateMap<Category, GetAllCategoryQueryDto>().ReverseMap();
        CreateMap<Category, GetByIdCategoryQueryDto>().ReverseMap();
    }
}

