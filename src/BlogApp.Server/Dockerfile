FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS base
WORKDIR /app
EXPOSE 8080

# SECURITY: Create intermediate stage with dependencies installed as root
FROM base AS base-with-deps
USER root
RUN apt-get update && apt-get install -y libgssapi-krb5-2 curl && rm -rf /var/lib/apt/lists/*

# SECURITY: Create non-root user
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid 1001 --shell /bin/sh --create-home appuser

FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

# Copy BuildingBlocks projects
COPY ["BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/BlogApp.BuildingBlocks.Caching.csproj", "BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Caching/"]
COPY ["BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Messaging/BlogApp.BuildingBlocks.Messaging.csproj", "BlogApp.BuildingBlocks/BlogApp.BuildingBlocks.Messaging/"]

# Copy BlogApp.Server projects
COPY ["BlogApp.Server/BlogApp.Server.Api/BlogApp.Server.Api.csproj", "BlogApp.Server/BlogApp.Server.Api/"]
COPY ["BlogApp.Server/BlogApp.Server.Application/BlogApp.Server.Application.csproj", "BlogApp.Server/BlogApp.Server.Application/"]
COPY ["BlogApp.Server/BlogApp.Server.Infrastructure/BlogApp.Server.Infrastructure.csproj", "BlogApp.Server/BlogApp.Server.Infrastructure/"]
COPY ["BlogApp.Server/BlogApp.Server.Domain/BlogApp.Server.Domain.csproj", "BlogApp.Server/BlogApp.Server.Domain/"]

RUN dotnet restore "BlogApp.Server/BlogApp.Server.Api/BlogApp.Server.Api.csproj"

COPY ["BlogApp.BuildingBlocks/", "BlogApp.BuildingBlocks/"]
COPY ["BlogApp.Server/", "BlogApp.Server/"]
WORKDIR "/src/BlogApp.Server/BlogApp.Server.Api"
RUN dotnet build "BlogApp.Server.Api.csproj" -c Release -o /app/build

FROM build AS publish
RUN dotnet publish "BlogApp.Server.Api.csproj" -c Release -o /app/publish /p:UseAppHost=false

FROM base-with-deps AS final
WORKDIR /app

# SECURITY: Copy with proper ownership
COPY --chown=appuser:appgroup --from=publish /app/publish .

# Create uploads directory with proper permissions (as root, then chown)
RUN mkdir -p /app/uploads && \
    chown appuser:appgroup /app/uploads && \
    chmod 755 /app/uploads

# SECURITY: Switch to non-root user
USER appuser

# Memory optimization for low-RAM servers
ENV DOTNET_GCHeapHardLimit=0x12C00000
ENV DOTNET_gcServer=0
ENV DOTNET_GCConserveMemory=9

ENTRYPOINT ["dotnet", "BlogApp.Server.Api.dll"]