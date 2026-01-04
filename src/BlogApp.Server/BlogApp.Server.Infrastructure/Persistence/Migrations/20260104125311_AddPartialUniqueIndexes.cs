using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace BlogApp.Server.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddPartialUniqueIndexes : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_tags_Slug",
                table: "tags");

            migrationBuilder.DropIndex(
                name: "IX_posts_Slug",
                table: "posts");

            migrationBuilder.DropIndex(
                name: "IX_categories_Slug",
                table: "categories");

            migrationBuilder.CreateIndex(
                name: "IX_tags_Name",
                table: "tags",
                column: "Name",
                unique: true,
                filter: "\"IsDeleted\" = false");

            migrationBuilder.CreateIndex(
                name: "IX_tags_Slug",
                table: "tags",
                column: "Slug",
                unique: true,
                filter: "\"IsDeleted\" = false");

            migrationBuilder.CreateIndex(
                name: "IX_posts_Slug",
                table: "posts",
                column: "Slug",
                unique: true,
                filter: "\"IsDeleted\" = false");

            migrationBuilder.CreateIndex(
                name: "IX_categories_Slug",
                table: "categories",
                column: "Slug",
                unique: true,
                filter: "\"IsDeleted\" = false");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_tags_Name",
                table: "tags");

            migrationBuilder.DropIndex(
                name: "IX_tags_Slug",
                table: "tags");

            migrationBuilder.DropIndex(
                name: "IX_posts_Slug",
                table: "posts");

            migrationBuilder.DropIndex(
                name: "IX_categories_Slug",
                table: "categories");

            migrationBuilder.CreateIndex(
                name: "IX_tags_Slug",
                table: "tags",
                column: "Slug",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_posts_Slug",
                table: "posts",
                column: "Slug",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_categories_Slug",
                table: "categories",
                column: "Slug",
                unique: true);
        }
    }
}
