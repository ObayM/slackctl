import time
import logging
import requests

class SlackPurger:
    """Handles authentication and deletion of user messages in a Slack channel."""

    def __init__(
        self,
        token: str,
        channel_id: str,
        dry_run: bool = True,
        rate_limit_sleep: float = 1.2,
        logger: logging.Logger | None = None
    ):
        self.token = token
        self.channel_id = channel_id
        self.dry_run = dry_run
        self.rate_limit_sleep = rate_limit_sleep
        self.headers = {"Authorization": f"Bearer {token}"}
        self.logger = logger or logging.getLogger(__name__)
        self.user_id = None
        self.username = None

    def _request_with_retry(self, method: str, url: str, **kwargs) -> dict:
        max_retries = 5
        for attempt in range(max_retries):
            try:
                resp = requests.request(method, url, **kwargs)
                
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 10))
                    self.logger.warning(f"Rate limited (HTTP 429). Retrying after {retry_after} seconds...")
                    time.sleep(retry_after)
                    continue

                resp.raise_for_status()
                data = resp.json()

                if not data.get("ok") and data.get("error") == "ratelimited":
                    retry_after = int(resp.headers.get("Retry-After", 10))
                    self.logger.warning(f"Rate limited (JSON error). Retrying after {retry_after} seconds...")
                    time.sleep(retry_after)
                    continue

                return data
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"Network error after {max_retries} attempts: {e}")
                    raise
                self.logger.warning(f"Network error: {e}. Retrying in 5 seconds...")
                time.sleep(5)

    def authenticate(self) -> str:
        self.logger.info("Connecting to Slack API and authenticating...")
        try:
            data = self._request_with_retry("GET", "https://slack.com/api/auth.test", headers=self.headers)
            if not data.get("ok"):
                raise RuntimeError(f"Authentication failed: {data.get('error')}")
            
            self.user_id = data["user_id"]
            self.username = data["user"]
            self.logger.info(f"Authenticated successfully as: {self.username} ({self.user_id})")
            return self.user_id
        except Exception as e:
            self.logger.error(f"Error during authentication: {e}")
            raise

    def delete_message(self, ts: str) -> dict:
        return self._request_with_retry(
            "POST",
            "https://slack.com/api/chat.delete",
            headers=self.headers,
            json={"channel": self.channel_id, "ts": ts},
        )

    def purge(self, limit: int = 100) -> dict:
        if not self.user_id:
            self.authenticate()

        self.logger.info(f"Targeting channel: {self.channel_id}")
        self.logger.info(f"Mode: {'DRY RUN (no messages will be deleted)' if self.dry_run else 'LIVE (messages will be permanently deleted)'}")

        stats = {
            "deleted": 0,
            "skipped": 0,
            "errors": 0
        }
        processed_ts = set()
        page = 1

        while True:
            query = f"from:<@{self.user_id}> in:<#{self.channel_id}>"
            self.logger.debug(f"Searching Slack messages with query: '{query}' (page: {page})")
            
            try:
                data = self._request_with_retry(
                    "GET",
                    "https://slack.com/api/search.messages",
                    headers=self.headers,
                    params={
                        "query": query,
                        "count": min(limit, 100),
                        "page": page,
                        "sort": "timestamp",
                        "sort_dir": "asc"
                    }
                )
            except Exception as e:
                self.logger.error(f"Failed to query search API: {e}")
                break

            if not data.get("ok"):
                error_msg = data.get("error", "unknown error")
                if error_msg == "missing_scope":
                    self.logger.error(
                        "Slack API error: missing_scope. "
                        "The 'search.messages' API requires the 'search:read' User OAuth scope. "
                        "Please go to your Slack App console, add 'search:read' user scope under OAuth & Permissions, "
                        "reinstall the app to your workspace, and try again."
                    )
                else:
                    self.logger.error(f"Slack API search error: {error_msg}")
                break

            messages_data = data.get("messages", {})
            matches = messages_data.get("matches", [])
            
            if not matches:
                self.logger.debug("No search matches found.")
                break

            self.logger.debug(f"Found {len(matches)} search matches on page {page}.")

            new_items_processed = 0
            successful_deletions = 0

            for msg in matches:
                ts = msg.get("ts")
                if not ts:
                    continue

                if ts in processed_ts:
                    continue

                processed_ts.add(ts)
                new_items_processed += 1
                
                msg_channel = msg.get("channel", {})
                msg_channel_id = msg_channel.get("id") if isinstance(msg_channel, dict) else msg_channel
                if msg_channel_id != self.channel_id:
                    self.logger.debug(f"Skipping search result in different channel: {msg_channel_id}")
                    stats["skipped"] += 1
                    continue

                preview = msg.get("text", "")[:60].replace("\n", " ")

                if self.dry_run:
                    self.logger.info(f"[DRY RUN] Would delete message [{ts}]: {preview!r}")
                    stats["deleted"] += 1
                else:
                    self.logger.info(f"Deleting message [{ts}]: {preview!r}")
                    try:
                        result = self.delete_message(ts)
                        if result.get("ok"):
                            self.logger.info(f"Successfully deleted message [{ts}]")
                            stats["deleted"] += 1
                            successful_deletions += 1
                        else:
                            err = result.get("error", "unknown error")
                            self.logger.error(f"Failed to delete message [{ts}]: {err}")
                            stats["errors"] += 1
                    except Exception as e:
                        self.logger.error(f"Exception deleting message [{ts}]: {e}")
                        stats["errors"] += 1

                    time.sleep(self.rate_limit_sleep)

            # Handle pagination when deleting:
            # - Dry run: advance pages normally.
            # - Live run: deleted items disappear from results, shifting future items to page 1.
            # Only advance the page index if we didn't perform any successful deletions on this page.
            if self.dry_run:
                page += 1
            else:
                if successful_deletions == 0:
                    page += 1
                else:
                    if new_items_processed == 0:
                        self.logger.debug("No new unprocessed matches on this page. Stopping.")
                        break

        self.logger.info("Purge process completed.")
        self.logger.info(
            f"Summary - {'Would delete' if self.dry_run else 'Deleted'}: {stats['deleted']}, "
            f"Skipped: {stats['skipped']}, Errors: {stats['errors']}"
        )
        return stats
