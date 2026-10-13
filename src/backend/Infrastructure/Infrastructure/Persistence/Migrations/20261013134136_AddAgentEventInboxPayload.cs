using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace BlogApp.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddAgentEventInboxPayload : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "PayloadJson",
                table: "agent_event_inbox",
                type: "text",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "ProgressMessage",
                table: "agent_event_inbox",
                type: "character varying(2000)",
                maxLength: 2000,
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "PayloadJson",
                table: "agent_event_inbox");

            migrationBuilder.DropColumn(
                name: "ProgressMessage",
                table: "agent_event_inbox");
        }
    }
}
