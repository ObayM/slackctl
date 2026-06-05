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
```bash
pip install slackctl
```

## config

you can pass your token and channel directly in the commands:
```bash
slackctl purge -t xoxp-your-token -c channel-id
```

or set them as global environment variables:
```bash
export SLACK_TOKEN="xoxp-your-token"
export SLACK_CHANNEL="channel-id"
```

or save them in a `.env` file in whatever directory you run the command from:
```env
SLACK_TOKEN="xoxp-your-token"
SLACK_CHANNEL="channel-id"
```

## commands

### purge
deletes your messages from the target channel.

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
