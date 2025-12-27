using AutoMapper;
using BlogApp.Server.Application.Features.CategoryFeature.DTOs;
using BlogApp.Server.Domain.Entities;

namespace BlogApp.Server.Application.Features.CategoryFeature.Mappings;

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
