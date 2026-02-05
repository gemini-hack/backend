# Architecture & Design

The Mira AI Backend follows a modular, service-oriented architecture built on **FastAPI**.

## Core Components

### 1. API Layer (`app/api/`)
*   **Routers**: Handle HTTP requests, validation, and response formatting.
*   **Dependencies**: Manage authentication, database sessions, and permissions.

### 2. Service Layer (`app/services/`)
*   Contains all business logic.
*   Separated from HTTP transport details.
*   Examples: `AuthService`, `PatientService`, `EmailService`.

### 3. Data Layer (`app/models/`, `app/db/`)
*   **SQLAlchemy Async**: ORM for database interactions.
*   **Alembic**: Database schema migrations.
*   **Pydantic Schemas**: Data validation and serialization.

### 4. Background Tasks (`app/tasks/`)
*   **Celery**: Distributed task queue for long-running operations.
*   **Redis**: Message broker and result backend.
*   Tasks include: Sending emails, processing AI analysis, importing data.

## External Integrations

*   **Google Gemini**: Generative AI for medical record analysis.
*   **LiveKit**: Real-time infrastructure for AI voice agents.
*   **Twilio/SIP**: Telephony integration for outbound calls.
