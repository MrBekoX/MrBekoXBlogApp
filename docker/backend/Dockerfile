# Build stage
FROM mcr.microsoft.com/dotnet/sdk:10.0@sha256:747cbade5bfd918a175ac32f8f1d931edec2c7d0d5397a3de72eaef1ac1f66d2 AS build
WORKDIR /src

# Copy solution and project files (layer cached until .csproj changes)
COPY ["BlogApp.sln", "./"]
COPY ["src/backend/Core/Domain/Domain.csproj", "src/backend/Core/Domain/"]
COPY ["src/backend/Core/Application/Application.csproj", "src/backend/Core/Application/"]
COPY ["src/backend/Infrastructure/Infrastructure/Infrastructure.csproj", "src/backend/Infrastructure/Infrastructure/"]
COPY ["src/backend/Presentation/API/API.csproj", "src/backend/Presentation/API/"]
COPY ["src/backend/BuildingBlocks/BuildingBlocks/BuildingBlocks.csproj", "src/backend/BuildingBlocks/BuildingBlocks/"]

# Restore dependencies (cached until .csproj/.sln changes)
RUN dotnet restore "src/backend/Presentation/API/API.csproj"

# Copy only backend source (not frontend)
COPY ["src/backend/", "src/backend/"]

# Canonical author profile (Who am I, K2/A33): API.csproj links ../../../content/author-profile/**
# into the publish output as content/author-profile/ (manifest.json, profile.json, source/**).
# Copied byte-for-byte; the runtime verifies sha256(profile.json) against manifest.content_hash.
COPY ["src/content/author-profile/manifest.json", "src/content/author-profile/profile.json", "src/content/author-profile/"]
COPY ["src/content/author-profile/source/", "src/content/author-profile/source/"]

# Publish directly (includes build - no need for separate dotnet build)
WORKDIR "/src/src/backend/Presentation/API"
RUN dotnet publish "API.csproj" -c Release -o /app/publish /p:UseAppHost=false

# Runtime stage
FROM mcr.microsoft.com/dotnet/aspnet:10.0@sha256:8af87eba5e7cdafb1514d7388be287365da97c132509e84dfe252ffd552398ca AS runtime
WORKDIR /app

# Install health check dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -g 1001 appgroup && \
    useradd -u 1001 -g appgroup -s /bin/bash -m appuser

# Copy published app
COPY --from=build /app/publish .

# Create uploads and DataProtection keys directories with proper ownership
RUN mkdir -p /app/uploads/images /app/keys && \
    chown -R appuser:appgroup /app /app/uploads /app/keys

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health/live || exit 1

# Set ASP.NET Core environment
ENV ASPNETCORE_URLS=http://+:8080
ENV ASPNETCORE_ENVIRONMENT=Production

ENTRYPOINT ["dotnet", "BlogApp.Presentation.Api.dll"]
