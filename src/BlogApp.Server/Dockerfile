FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS base
WORKDIR /app
EXPOSE 8080

FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

COPY ["BlogApp.Server.Api/BlogApp.Server.Api.csproj", "BlogApp.Server.Api/"]
COPY ["BlogApp.Server.Application/BlogApp.Server.Application.csproj", "BlogApp.Server.Application/"]
COPY ["BlogApp.Server.Infrastructure/BlogApp.Server.Infrastructure.csproj", "BlogApp.Server.Infrastructure/"]
COPY ["BlogApp.Server.Domain/BlogApp.Server.Domain.csproj", "BlogApp.Server.Domain/"]

RUN dotnet restore "BlogApp.Server.Api/BlogApp.Server.Api.csproj"

COPY . .
WORKDIR "/src/BlogApp.Server.Api"
RUN dotnet build "BlogApp.Server.Api.csproj" -c Release -o /app/build

FROM build AS publish
RUN dotnet publish "BlogApp.Server.Api.csproj" -c Release -o /app/publish /p:UseAppHost=false

FROM base AS final
WORKDIR /app

# Eksik kütüphaneyi root olarak yükle
USER root
RUN apt-get update && apt-get install -y libgssapi-krb5-2 && rm -rf /var/lib/apt/lists/*

# Kullanıcıyı oluştur
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid 1001 --shell /bin/sh --create-home appuser

COPY --from=publish /app/publish .

RUN mkdir -p /app/uploads && \
    chown -R appuser:appgroup /app/uploads && \
    chmod 755 /app/uploads

USER appuser
ENTRYPOINT ["dotnet", "BlogApp.Server.Api.dll"]