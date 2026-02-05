# Agent System API Guide & Testing Manual

## 🚀 How to Test the Agent System

You can test the autonomous agents using `curl` or your browser's Swagger UI (`/docs`).

### 1. Trigger "Morning Rounds" (Manual Run)
The agents usually run on a schedule, but you can force a run to see immediate results.

**Endpoint:** `POST /api/v1/agents/trigger-rounds`
**Description:** Starts the `DailyAnalysisWorkflow` in the background.

```bash
curl -X POST "http://localhost:8000/api/v1/agents/trigger-rounds" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```
*Response: 202 Accepted {"message": "Analysis rounds triggered in background"}*

### 2. View Agent Decisions
After triggering, wait a few seconds/minutes for the analysis to complete. Then fetch the actions taken.

**Endpoint:** `GET /api/v1/agents/actions`
**Description:** Returns a history of what the agents decided and executed.

```bash
curl -X GET "http://localhost:8000/api/v1/agents/actions?limit=20" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### 3. View Generated Alerts
If the agents found critical issues (e.g., High Viral Load, IIT), they create Alerts.

**Endpoint:** `GET /api/v1/agents/alerts`
**Description:** Returns active alerts requiring human attention.

---

## 💻 Frontend Developer Reference

Here are the endpoints you need to integrate MIRA's transparency layer into the UI.

### 1. Agent Activity Feed
**Use Case:** Show a "Live Feed" of what MIRA is doing (e.g., "Sent SMS to Patient X", "Flagged Patient Y").

- **GET** `/agents/actions`
- **Response Type:** `List[AgentAction]`
- **Key Fields:**
  - `action_type` (string): e.g., `schedule_appointment_reminder`, `initiate_art`.
  - `status` (string): `completed` (green), `pending` (yellow), `failed` (red).
  - `ai_reasoning` (string): The "Why" behind the action. Display this in a tooltip or expanded view.
  - `content` (json): Details like `appointment_id`, `viral_load`, etc.

### 2. Clinical Alerts Dashboard
**Use Case:** The "Inbox" for doctors to review high-risk patients caught by MIRA.

- **GET** `/agents/alerts?status=pending`
- **Response Type:** `List[Alert]`
- **Key Fields:**
  - `severity` (string): `critical`, `urgent`, `warning`.
  - `title` (string): e.g., "Unsuppressed Viral Load".
  - `ai_assessment` (json): Clinical data backing the alert.

### 3. Manual Trigger Button
**Use Case:** A "Run Analysis Now" button in the Settings > Agents panel.

- **POST** `/agents/trigger-rounds`
- **UX Tip:** Show a spinner/toast notification saying "MIRA is analyzing patient data..." after clicking.

### 4. Configuration
**Use Case:** Allow admins to select which diseases MIRA monitors.

- **PATCH** `/agents/config`
- **Payload:** `{ "disease_specializations": ["hiv", "hypertension"] }`