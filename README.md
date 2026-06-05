# slackctl

cli tool to clear out your slack messages or export them to a neat dashboard.

## setup

### slack app permissions
you need to build a quick slack app to get a token:
1. head to https://api.slack.com/apps and create a new app from scratch.
2. add these user scopes under oauth and permissions:
   - channels:history
   - groups:history
   - chat:write
   - search:read
3. click install to workspace and copy the token starting with xoxp-.

### install
make sure your python venv is active, then run:
```bash
pip install -e .
```

## config
save your credentials in a `.env` file so you don't have to keep pasting them:
```env
SLACK_TOKEN="xoxp-your-token-here"
SLACK_CHANNEL="your-channel-id-here"
```

## commands

### purge
deletes your messages from the target channel using slack's search api.

dry run (safely checks what would get deleted):
```bash
slackctl purge
```

live run (actually deletes everything):
```bash
slackctl purge --no-dry-run
```

### export
saves your message history to an offline html dashboard or raw data formats.

build html dashboard:
```bash
slackctl export
```

other formats:
```bash
slackctl export --format markdown -o messages.md
slackctl export --format json -o messages.json
```
