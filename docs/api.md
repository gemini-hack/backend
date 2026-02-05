# API Reference

## Authentication

### Login
`POST /api/v1/auth/access-token`

Obtain an OAuth2 compatible access token.

**Request Body**: `OAuth2PasswordRequestForm` (username, password)

**Response**:
```json
{
  "access_token": "eyJhbG...",
  "token_type": "bearer"
}
```

### Signup
`POST /api/v1/auth/signup`

Register a new user account.

## Users

### Get Current User
`GET /api/v1/users/me`

Retrieve profile information for the authenticated user.

## Patients

### List Patients
`GET /api/v1/patients/`

List all patients with pagination support.

### Create Patient
`POST /api/v1/patients/`

Register a new patient record.

## Calls (Voice AI)

### Initiate Outbound Call
`POST /api/v1/calls/outbound`

Trigger an AI voice agent call to a patient.
