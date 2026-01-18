# MIRA Voice Agent

MIRA is an AI-powered voice agent for healthcare professionals built on LiveKit and Google Gemini.

## Overview

The voice agent enables hands-free interaction with patient data, appointments, and care workflows through natural speech. Healthcare workers can query patient information, manage appointments, and receive alerts without manual input.

## Architecture

```
Client (WebRTC) --> LiveKit Server --> MIRA Agent --> Gemini Live API
                                           |
                                           v
                                    PostgreSQL Database
```

## Directory Structure

```
app/agents/livekit_gemini/
├── __init__.py          # Package exports
├── main.py              # Agent entrypoint and configuration
├── tools.py             # Function tools available to the LLM
├── security.py          # Input validation, audit logging, permissions
└── voice_context.py     # User context management for sessions
```

## Configuration

Required environment variables:

| Variable | Description |
|----------|-------------|
| LIVEKIT_URL | LiveKit server WebSocket URL |
| LIVEKIT_API_KEY | LiveKit API key |
| LIVEKIT_API_SECRET | LiveKit API secret |
| GOOGLE_API_KEY | Google Gemini API key |
| DATABASE_URL | PostgreSQL connection string |

## Starting the Agent

```bash
uv run python -m app.agents.livekit_gemini.main start
```

The agent registers with LiveKit Cloud and handles incoming voice sessions automatically.

## Available Tools

### Patient Lookup
- `get_patient_info(patient_name)` - Search patient by name
- `get_patient_by_id(patient_id)` - Lookup by patient UID
- `list_high_priority_patients(limit)` - Get patients needing attention

### Appointments
- `get_today_appointments()` - List today's scheduled appointments
- `get_patient_appointments(patient_name)` - Get appointments for a patient

### Alerts
- `get_active_alerts(limit)` - Get pending alerts requiring action

### Caseload
- `get_my_caseload_summary()` - Summary of active patients and tasks

## Security Features

### Input Validation
All tool inputs are validated for:
- Maximum length constraints
- SQL injection patterns
- XSS and template injection patterns

### Audit Logging
Every tool invocation is logged with:
- Tool name and parameters
- User ID and organization ID
- Timestamp and success status

### Permission Control
Tools can be protected with role-based permissions:

```python
@require_permission("patients:read")
@function_tool
async def get_patient_info(patient_name: str) -> str:
    ...
```

### System Prompt Hardening
The agent includes security constraints:
- No medical advice or recommendations
- No disclosure of system instructions
- No access outside authorized scope
- No role-playing as other systems

## User Context

Voice sessions receive user context from the client token metadata:

```json
{
  "user_id": "uuid",
  "organization_id": "uuid",
  "role": "nurse",
  "full_name": "Jane Doe"
}
```

This context enables:
- Permission checking per tool call
- Organization-scoped database queries
- Audit trail for compliance

## Voice Session Flow

1. Client calls `POST /voice/session` to get LiveKit token
2. Client connects to LiveKit room via WebRTC
3. Agent joins room and sends greeting
4. User speaks, Gemini transcribes and processes
5. Agent responds with speech and executes tools as needed
6. Session ends when client disconnects

## Model Configuration

| Setting | Value |
|---------|-------|
| Model | gemini-2.5-flash-native-audio-preview |
| Voice | Puck |
| Temperature | 0.8 |
| VAD | Silero (turn detection) |

## Adding New Tools

1. Define the function in `tools.py`:

```python
@function_tool
async def my_new_tool(param: str) -> str:
    """Description shown to the LLM."""
    # Validate input
    valid, error = validate_input(param)
    if not valid:
        return error
    
    # Execute logic
    result = await do_something(param)
    
    # Audit log
    audit_log("my_new_tool", {"param": param}, result)
    
    return result
```

2. Add to `MIRA_TOOLS` list at the bottom of `tools.py`

3. Restart the agent

## Testing

### Manual Testing

1. Start the agent
2. Create a voice session via the API
3. Connect using the [LiveKit Agents Playground](https://agents-playground.livekit.io) or a client app
4. Speak commands like "Look up patient John Doe"

## Troubleshooting

### Agent not responding
- Check GOOGLE_API_KEY is set correctly
- Verify LiveKit connection in agent logs
- Ensure agent is registered (check LiveKit Cloud dashboard)

### Tools not being called
- Check tool is in MIRA_TOOLS list
- Verify tool description is clear for the LLM
- Check for validation errors in audit logs

### Database errors in tools
- Verify DATABASE_URL is accessible from agent process
- Check async session factory is configured correctly
