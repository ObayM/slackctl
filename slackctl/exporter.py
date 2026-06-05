import json
import logging
import time
import datetime
from pathlib import Path
import requests

class SlackExporter:
    """Handles fetching and exporting user messages across all or specific Slack channels."""

    def __init__(
        self,
        token: str,
        channel_id: str | None = None,
        logger: logging.Logger | None = None
    ):
        self.token = token
        self.channel_id = channel_id
        self.headers = {"Authorization": f"Bearer {token}"}
        self.logger = logger or logging.getLogger(__name__)
        self.user_id = None
        self.username = None

    def _request_with_retry(self, method: str, url: str, **kwargs) -> dict:
        """Helper to send HTTP requests with support for automatic 429 rate limit retries."""
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
        """Verify credentials and retrieve User ID."""
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

    def fetch_all_messages(self, limit: int = 100) -> list:
        """Fetch all messages sent by this user using the search API."""
        if not self.user_id:
            self.authenticate()

        query = f"from:<@{self.user_id}>"
        if self.channel_id:
            query += f" in:<#{self.channel_id}>"
            self.logger.info(f"Searching for messages in channel {self.channel_id}...")
        else:
            self.logger.info("Searching for your messages across all accessible channels...")

        all_messages = []
        page = 1

        while True:
            self.logger.debug(f"Querying search page {page}...")
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
                self.logger.error(f"Slack API search error: {data.get('error')}")
                break

            messages_data = data.get("messages", {})
            matches = messages_data.get("matches", [])
            
            if not matches:
                break

            for msg in matches:
                channel_info = msg.get("channel", {})
                ch_id = channel_info.get("id") if isinstance(channel_info, dict) else channel_info
                ch_name = channel_info.get("name") if isinstance(channel_info, dict) else ""

                all_messages.append({
                    "ts": msg.get("ts"),
                    "text": msg.get("text", ""),
                    "channel_id": ch_id,
                    "channel_name": ch_name,
                    "permalink": msg.get("permalink", ""),
                    "username": msg.get("username", self.username),
                    "user_id": msg.get("user", self.user_id)
                })

            self.logger.info(f"Fetched {len(all_messages)} messages so far...")

            paging = messages_data.get("paging", {})
            total_pages = paging.get("pages", 1)
            if page >= total_pages:
                break
            page += 1
            time.sleep(0.5)

        self.logger.info(f"Retrieved {len(all_messages)} messages total.")
        return all_messages

    def export(self, output_path: str, format_type: str) -> None:
        """Run fetch and format/save to output file."""
        messages = self.fetch_all_messages()

        if format_type.lower() == "json":
            self._export_json(messages, output_path)
        elif format_type.lower() == "markdown":
            self._export_markdown(messages, output_path)
        else:
            self._export_html(messages, output_path)

    def _export_json(self, messages: list, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "meta": {
                    "username": self.username,
                    "user_id": self.user_id,
                    "exported_at": datetime.datetime.now().isoformat(),
                    "total_messages": len(messages)
                },
                "messages": messages
            }, f, indent=2, ensure_ascii=False)
        self.logger.info(f"JSON export saved to: {path}")

    def _export_markdown(self, messages: list, path: str) -> None:
        messages_sorted = sorted(messages, key=lambda x: float(x.get("ts") or 0))
        lines = [
            f"# Slack Message Export for @{self.username}",
            f"- **User ID**: `{self.user_id}`",
            f"- **Export Date**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **Total Messages**: {len(messages)}",
            "",
            "---",
            ""
        ]

        grouped = {}
        for m in messages_sorted:
            ch = m.get("channel_name") or m.get("channel_id") or "unknown-channel"
            grouped.setdefault(ch, []).append(m)

        for channel, msgs in sorted(grouped.items()):
            lines.append(f"## Channel: #{channel}")
            for m in msgs:
                try:
                    dt = datetime.datetime.fromtimestamp(float(m["ts"])).strftime("%Y-%m-%d %H:%M:%S")
                except:
                    dt = m.get("ts")
                
                text = m.get("text", "").replace("\n", " ")
                link = f" ([Link]({m['permalink']}))" if m.get("permalink") else ""
                lines.append(f"- **[{dt}]**: {text}{link}")
            lines.append("")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        self.logger.info(f"Markdown export saved to: {path}")

    def _export_html(self, messages: list, path: str) -> None:
        messages_sorted = sorted(messages, key=lambda x: float(x.get("ts") or 0))
        
        for m in messages_sorted:
            try:
                m["formatted_date"] = datetime.datetime.fromtimestamp(float(m["ts"])).strftime("%Y-%m-%d %H:%M:%S")
            except:
                m["formatted_date"] = m.get("ts", "")

        channel_counts = {}
        for m in messages_sorted:
            ch_name = m.get("channel_name") or m.get("channel_id") or "unknown"
            channel_counts[ch_name] = channel_counts.get(ch_name, 0) + 1

        channels_list = [{"name": name, "count": count} for name, count in sorted(channel_counts.items())]

        html_content = self._get_html_template(messages_sorted, channels_list)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_content)
        self.logger.info(f"Beautiful HTML report saved to: {path}")

    def _get_html_template(self, messages: list, channels: list) -> str:
        messages_json = json.dumps(messages)
        channels_json = json.dumps(channels)
        
        templates_dir = Path(__file__).parent / "templates"
        try:
            with open(templates_dir / "index.html", "r", encoding="utf-8") as f:
                index_html = f.read()
            with open(templates_dir / "style.css", "r", encoding="utf-8") as f:
                style_css = f.read()
            with open(templates_dir / "app.js", "r", encoding="utf-8") as f:
                app_js = f.read()
        except Exception as e:
            self.logger.error(f"Failed to load HTML templates from {templates_dir}: {e}")
            raise

        template = (
            index_html
            .replace("{{css_content}}", style_css)
            .replace("{{js_content}}", app_js)
        )

        return (
            template
            .replace("{{username}}", self.username or "")
            .replace("{{user_id}}", self.user_id or "")
            .replace("{{messages_count}}", str(len(messages)))
            .replace("{{channels_count}}", str(len(channels)))
            .replace("{{messages_json}}", messages_json)
            .replace("{{channels_json}}", channels_json)
        )
