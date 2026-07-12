FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Set environment variables for Poetry
ENV POETRY_VERSION=1.8.2 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_CREATE=false \
    PATH="/opt/poetry/bin:$PATH"

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -

WORKDIR /app

# Copy dependency definition files
COPY pyproject.toml poetry.lock ./

# Install dependencies using Poetry
RUN poetry install --no-root

# Install Scrapling's browser engines and dependencies
RUN scrapling install || (playwright install chromium && playwright install-deps chromium)

# Copy the rest of the application code
COPY . .

CMD ["python", "main.py"]
