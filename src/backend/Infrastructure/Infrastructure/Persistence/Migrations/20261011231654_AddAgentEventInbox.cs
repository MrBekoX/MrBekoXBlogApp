using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace BlogApp.Infrastructure.Persistence.Migrations
{
    /// <inheritdoc />
    public partial class AddAgentEventInbox : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<long>(
                name: "LastEventSequence",
                table: "agent_runs",
                type: "bigint",
                nullable: false,
                defaultValue: 0L);

            migrationBuilder.AddColumn<string>(
                name: "ResultJson",
                table: "agent_runs",
                type: "jsonb",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "SelectedMode",
                table: "agent_runs",
                type: "character varying(16)",
                maxLength: 16,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "SourceScope",
                table: "agent_runs",
                type: "character varying(24)",
                maxLength: 24,
                nullable: true);

            migrationBuilder.AddColumn<DateTime>(
                name: "TerminalAt",
                table: "agent_runs",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.CreateTable(
                name: "agent_event_inbox",
                columns: table => new
                {
                    ConsumerName = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    MessageId = table.Column<Guid>(type: "uuid", nullable: false),
                    MessageType = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    RunId = table.Column<Guid>(type: "uuid", nullable: true),
                    EventSequence = table.Column<long>(type: "bigint", nullable: false),
                    Status = table.Column<string>(type: "character varying(16)", maxLength: 16, nullable: false),
                    Detail = table.Column<string>(type: "character varying(512)", maxLength: 512, nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_agent_event_inbox", x => new { x.ConsumerName, x.MessageId });
                });

            migrationBuilder.CreateIndex(
                name: "IX_agent_event_inbox_run",
                table: "agent_event_inbox",
                column: "RunId");

            migrationBuilder.CreateIndex(
                name: "IX_agent_event_inbox_status",
                table: "agent_event_inbox",
                column: "Status");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "agent_event_inbox");

            migrationBuilder.DropColumn(
                name: "LastEventSequence",
                table: "agent_runs");

            migrationBuilder.DropColumn(
                name: "ResultJson",
                table: "agent_runs");

            migrationBuilder.DropColumn(
                name: "SelectedMode",
                table: "agent_runs");

            migrationBuilder.DropColumn(
                name: "SourceScope",
                table: "agent_runs");

            migrationBuilder.DropColumn(
                name: "TerminalAt",
                table: "agent_runs");
        }
    }
}
