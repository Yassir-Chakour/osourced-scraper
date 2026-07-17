# Use official Playwright Python image pre-configured with browser dependencies
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Set environment variables for Python and Poetry
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=1.8.2 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_CREATE=false \
    PATH="/opt/poetry/bin:$PATH"

# Install Poetry and clean apt cache in a single layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && curl -sSL https://install.python-poetry.org | python3 - \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files first to leverage Docker layer caching
COPY pyproject.toml poetry.lock ./

# Install dependencies (only main production packages, no dev dependencies)
RUN poetry install --no-root --no-interaction --no-ansi --only main \
    && poetry cache clear pypi --all

# Install Scrapling's browser engines and dependencies (specifically Chromium)
RUN scrapling install || (playwright install chromium && playwright install-deps chromium)

# Copy the rest of the application code
COPY . .

# Default command to run the scraper
CMD ["python", "main.py"]
