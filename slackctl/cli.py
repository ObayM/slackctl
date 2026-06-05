import os
from pathlib import Path
import logging
import sys
import click

from slackctl.purger import SlackPurger
from slackctl.exporter import SlackExporter

def load_dotenv(dotenv_path: str = ".env") -> None:
    """Load environment variables from a .env file if it exists."""
    path = Path(dotenv_path)
    if not path.is_file():
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    if val.startswith('"'):
                        end_idx = val.find('"', 1)
                        if end_idx != -1:
                            val = val[1:end_idx]
                    elif val.startswith("'"):
                        end_idx = val.find("'", 1)
                        if end_idx != -1:
                            val = val[1:end_idx]
                    else:
                        if " #" in val:
                            val = val.split(" #", 1)[0].strip()
                        elif val.startswith("#"):
                            val = ""
                    if key and key not in os.environ:
                        os.environ[key] = val
    except Exception:
        pass

load_dotenv()

def setup_logging(log_file: str, verbose: bool) -> logging.Logger:
    """Set up the application logger with console and file destinations."""
    logger = logging.getLogger("slackctl")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    logger.handlers.clear()

    console_level = logging.DEBUG if verbose else logging.INFO
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_formatter = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s"
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            click.echo(f"Warning: Could not configure log file {log_file}: {e}", err=True)

    return logger

@click.group()
def main():
    """slackctl: A collection of handy CLI utilities for Slack."""
    pass

@main.command("purge")
@click.option(
    "--token", "-t",
    envvar="SLACK_TOKEN",
    help="Slack User OAuth Token (starts with xoxp-). Can also be set via SLACK_TOKEN environment variable.",
)
@click.option(
    "--channel", "-c",
    envvar="SLACK_CHANNEL",
    help="Target Slack Channel ID. Can also be set via SLACK_CHANNEL environment variable.",
)
@click.option(
    "--dry-run/--no-dry-run",
    default=True,
    show_default=True,
    help="Dry run mode (list messages that would be deleted, without actually deleting them).",
)
@click.option(
    "--yes", "-y",
    is_flag=True,
    help="Skip safety confirmation prompt when running in live mode (--no-dry-run).",
)
@click.option(
    "--limit", "-l",
    default=200,
    show_default=True,
    help="Max messages to request per fetch request.",
)
@click.option(
    "--sleep", "-s",
    default=1.2,
    show_default=True,
    help="Delay in seconds between deletion requests (Slack rate limit is approx 1 req/sec).",
)
@click.option(
    "--log-file",
    default="slack_wipe.log",
    show_default=True,
    help="Path to file where detailed logs will be written.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Show verbose output in the terminal (including reasons for skipped messages).",
)
def purge(token, channel, dry_run, yes, limit, sleep, log_file, verbose):
    """Safely bulk-delete your messages from a Slack channel."""
    logger = setup_logging(log_file, verbose)

    if not token:
        logger.error("Slack Token is required. Use --token/-t or set SLACK_TOKEN environment variable.")
        sys.exit(1)

    if not channel:
        logger.error("Slack Channel ID is required. Use --channel/-c or set SLACK_CHANNEL environment variable.")
        sys.exit(1)

    if not dry_run and not yes:
        msg = f"WARNING: You are about to permanently delete your messages in channel {channel}. This cannot be undone! Continue?"
        if not click.confirm(msg, default=False):
            logger.info("Purge cancelled by user.")
            sys.exit(0)

    purger = SlackPurger(
        token=token,
        channel_id=channel,
        dry_run=dry_run,
        rate_limit_sleep=sleep,
        logger=logger
    )

    try:
        purger.purge(limit=limit)
    except Exception as e:
        logger.critical(f"Execution failed: {e}")
        sys.exit(2)

@main.command("export")
@click.option(
    "--token", "-t",
    envvar="SLACK_TOKEN",
    help="Slack User OAuth Token (starts with xoxp-). Can also be set via SLACK_TOKEN environment variable.",
)
@click.option(
    "--channel", "-c",
    envvar="SLACK_CHANNEL",
    help="Optional target Slack Channel ID. If omitted, exports every message you ever sent across all channels.",
)
@click.option(
    "--output", "-o",
    default="slack_export.html",
    show_default=True,
    help="Path to output file where the export will be saved.",
)
@click.option(
    "--format", "-f",
    type=click.Choice(["html", "json", "markdown"], case_sensitive=False),
    default="html",
    show_default=True,
    help="Export output format: 'html' (interactive dashboard), 'json' (raw data), 'markdown' (readable log).",
)
@click.option(
    "--log-file",
    default="slack_export.log",
    show_default=True,
    help="Path to file where detailed logs will be written.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Show verbose output in the terminal.",
)
def export(token, channel, output, format, log_file, verbose):
    """Export all your messages in a specific channel or across all Slack channels."""
    logger = setup_logging(log_file, verbose)

    if not token:
        logger.error("Slack Token is required. Use --token/-t or set SLACK_TOKEN environment variable.")
        sys.exit(1)

    exporter = SlackExporter(
        token=token,
        channel_id=channel,
        logger=logger
    )

    try:
        exporter.export(output_path=output, format_type=format)
    except Exception as e:
        logger.critical(f"Export failed: {e}")
        sys.exit(2)

def wipe_compat():
    """Compatibility alias to run 'purge' directly when 'slack-wipe' is called."""
    # Inject 'purge' into argv so Click routes to the purge command
    sys.argv.insert(1, "purge")
    main()

if __name__ == "__main__":
    main()
