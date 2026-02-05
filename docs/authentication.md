# Authentication

We use **OAuth2 with Password Flow** and **JWT (JSON Web Tokens)** for securing the API.

## Security Model

1.  **Access Tokens**: Short-lived tokens (expires in 15 minutes) used for API access.
2.  **Refresh Tokens**: Long-lived tokens (expires in 7 days) used to obtain new access tokens.
3.  **Password Hashing**: Passwords are hashed using `bcrypt`.

## Flows

### Registration
Users sign up via the `/signup` endpoint. This creates a new `User` record in the database.

### Login
1.  Client sends `username` (email) and `password` to `/login`.
2.  Server verifies credentials.
3.  Server returns `access_token` and `refresh_token`.

### Protected Endpoints
Include the token in the `Authorization` header:

```http
Authorization: Bearer <your_access_token>
```
