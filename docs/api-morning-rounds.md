# Morning Rounds API - Frontend Integration Guide

This document explains how the AI agent system works and how to integrate with the frontend.

---

## Overview

The AI performs **morning rounds** - analyzing all patients and generating actions/alerts. There are two ways this happens:

| Method | Schedule | Frontend Action |
|--------|----------|-----------------|
| **Automatic** | 6 AM UTC daily | Connect WebSocket → receive updates |
| **Manual** | Admin clicks button | Trigger → watch SSE stream → refresh |

---

## 1. WebSocket - Real-Time Dashboard Updates

**Connect once when user logs in.** Receive push notifications when:
- Morning rounds complete
- New actions/alerts created

### Endpoint
```
WS /api/v1/agents/dashboard/ws?token=<JWT_ACCESS_TOKEN>
```

### JavaScript Example
```javascript
const token = localStorage.getItem('accessToken');
const ws = new WebSocket(`wss://your-api.com/api/v1/agents/dashboard/ws?token=${token}`);

ws.onopen = () => {
    console.log('Connected to dashboard notifications');
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    switch (data.type) {
        case 'connected':
            console.log('WebSocket connected');
            break;
            
        case 'cycle_completed':
            // Morning rounds finished - refresh the dashboard!
            console.log(`New actions: ${data.data.actions_count}`);
            console.log(`New alerts: ${data.data.alerts_count}`);
            refreshDashboard();
            break;
    }
};

ws.onclose = () => {
    // Reconnect after 5 seconds
    setTimeout(connectWebSocket, 5000);
};
```

### Message Types

| Type | When | Data |
|------|------|------|
| `connected` | WebSocket opens | `{ channel, message }` |
| `cycle_completed` | Morning rounds finish | `{ cycle_id, actions_count, alerts_count }` |

---

## 2. Manual Trigger - Real-Time Thought Stream

For admin dashboards that want to trigger analysis manually and watch the AI think.

### Step 1: Trigger Analysis

```
POST /api/v1/agents/trigger-rounds
Authorization: Bearer <token>
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "cycle_id": "abc-123-uuid",
        "message": "Morning rounds started"
    }
}
```

### Step 2: Subscribe to Thought Stream (SSE)

```
GET /api/v1/agents/stream/<cycle_id>?token=<JWT_TOKEN>
```

### JavaScript Example

```javascript
async function triggerAndWatch() {
    // 1. Trigger analysis
    const response = await fetch('/api/v1/agents/trigger-rounds', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
    });
    const { data } = await response.json();
    const cycleId = data.cycle_id;
    
    // 2. Subscribe to thought stream
    const eventSource = new EventSource(
        `/api/v1/agents/stream/${cycleId}?token=${token}`
    );
    
    eventSource.onmessage = (event) => {
        const thought = JSON.parse(event.data);
        
        // Display in UI
        displayThought({
            agent: thought.agent_name,      // "hiv_specialist"
            stage: thought.stage,           // "specialist_analysis"
            content: thought.content,       // "🔬 Analyzing patient..."
            timestamp: thought.timestamp
        });
    };
    
    eventSource.addEventListener('done', () => {
        eventSource.close();
        refreshDashboard();
    });
    
    eventSource.onerror = () => {
        eventSource.close();
    };
}
```

### Thought Event Format

```json
{
    "cycle_id": "uuid",
    "timestamp": "2026-01-30T15:00:00Z",
    "agent_name": "hiv_specialist",
    "stage": "specialist_analysis",
    "content": "🔬 Analyzing viral load for patient John Doe...",
    "patient_id": "uuid or null",
    "metadata": {}
}
```

### Stages (in order)

1. `loading_data` - Loading patient records
2. `specialist_analysis` - Specialists analyzing patients
3. `supervisor_synthesis` - Merging recommendations
4. `auto_execution` - Sending automated reminders
5. `critic_review` - Quality check
6. `persist_actions` - Saving to database
7. `complete` - Done

---

## 3. Fetching Actions & Alerts

### List All Actions
```
GET /api/v1/agents/actions?limit=50&assigned_to_me=false
Authorization: Bearer <token>
```

**Query Params:**
- `limit` - Max results (default: 50)
- `assigned_to_me` - Filter to user's patients only

### List Resolved Actions
```
GET /api/v1/agents/actions/resolved?limit=100&offset=0
```

**Query Params:**
- `action_type` - Filter by type
- `from_date` - Start date
- `to_date` - End date

### Manually Resolve an Action
```
POST /api/v1/agents/actions/<action_id>/resolve?reason=Patient confirmed via phone
Authorization: Bearer <token>
```

### List Alerts
```
GET /api/v1/agents/alerts?alert_status=pending&limit=50
Authorization: Bearer <token>
```

---

## 4. Patient Details with Actions

When fetching a single patient, actions are included:

```
GET /api/v1/patients/<patient_id>
```

**Response includes:**
```json
{
    "data": {
        "first_name": "John",
        "agent_actions": [
            {
                "action_type": "engagement_nudge",
                "status": "completed",
                "ai_reasoning": "Patient hasn't submitted reading in 7 days",
                "decision_trace": { ... }
            }
        ],
        "alerts": [ ... ]
    }
}
```

---

## Quick Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `WS /agents/dashboard/ws?token=JWT` | WebSocket | Live dashboard updates |
| `POST /agents/trigger-rounds` | POST | Manual trigger |
| `GET /agents/stream/{cycle_id}` | SSE | Watch AI think |
| `GET /agents/actions` | GET | List all actions |
| `GET /agents/actions/resolved` | GET | List resolved actions |
| `POST /agents/actions/{id}/resolve` | POST | Manually resolve |
| `GET /agents/alerts` | GET | List alerts |
