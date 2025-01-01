# Work Hours Calendar

A FastAPI service that generates SVG calendars visualizing work hours logged in Jira. The calendar shows daily work hours, running totals, and statistics for the month.

## Features

- Monthly calendar view with daily work hours
- Color-coded work hour indicators
- Running total calculations
- Statistics including average hours and required hours to balance
- Support for annual leave tracking
- Secure access using HMAC authentication

## Requirements

- Python 3.12+
- Docker (optional)

## Installation

1. Clone the repository
2. Create a `.env` file with:
```
JIRA_API_TOKEN=your_jira_token
HASH_SECRET_KEY=your_secret_key
JIRA_URL=https://jira.example.com
```

## Running the Service

### Using Docker

```bash
docker compose up
```

### Without Docker

```bash
# Install dependencies
uv install

# Run the service
uv run fastapi run hello.py
```

## Usage

Generate a calendar by making a GET request to `/calendar` with the following parameters:
- `year`: Year (2000-2100)
- `month`: Month (1-12)
- `username`: Jira username
- `hash`: HMAC authentication hash

To generate the required hash, use:
```python
python3 -c 'import hmac, hashlib; year=2024; month=3; username="your_username"; secret="your_secret_key"; print(hmac.new(secret.encode("utf-8"), f"{year}-{month}-{username}".encode("utf-8"), hashlib.sha256).hexdigest())'
```

Example URL:
```
http://localhost:4012/calendar?year=2024&month=3&username=john.doe&hash=generated_hash
```

The service will return an SVG image showing the work hours calendar for the specified month.