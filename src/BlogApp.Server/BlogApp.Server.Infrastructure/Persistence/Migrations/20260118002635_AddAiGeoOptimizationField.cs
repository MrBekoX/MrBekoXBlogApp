using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace BlogApp.Server.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddAiGeoOptimizationField : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_refresh_tokens_Token",
                table: "refresh_tokens");

            migrationBuilder.AddColumn<string>(
                name: "AiGeoOptimization",
                table: "posts",
                type: "text",
                nullable: true);

            migrationBuilder.CreateIndex(
                name: "IX_refresh_tokens_Token",
                table: "refresh_tokens",
                column: "Token",
                unique: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_refresh_tokens_Token",
                table: "refresh_tokens");

            migrationBuilder.DropColumn(
                name: "AiGeoOptimization",
                table: "posts");

            migrationBuilder.CreateIndex(
                name: "IX_refresh_tokens_Token",
                table: "refresh_tokens",
                column: "Token");
        }
    }
}
