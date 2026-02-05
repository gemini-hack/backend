# Getting Started

Follow this guide to set up the Mira AI Backend for local development.

## Prerequisites

*   **Docker & Docker Compose**: Essential for running services.
*   **Python 3.12+**: For local development (optional if using Docker).
*   **uv**: Fast Python package installer and resolver.

## Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/gemini-hack/backend.git
    cd backend
    ```

2.  **Environment Variables**:
    Copy the sample environment file:
    ```bash
    cp .env.sample .env
    ```
    Update `.env` with your credentials (database, API keys, etc.).

3.  **Run with Docker Compose**:
    This starts the API, Database, Redis, and Celery worker.
    ```bash
    docker compose up --build
    ```

    The API will be available at `http://localhost:8000`.

## Development

To run commands/migrations inside the container:

```bash
# Run migrations
docker compose exec api alembic upgrade head

# Run tests
docker compose exec api pytest
```
