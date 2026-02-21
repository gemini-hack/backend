from app.models.user import UserRole

# Define available permissions
# Format: "resource:action"

# Permission Constants
PERM_INVITATIONS_CREATE = "invitations:create"
PERM_INVITATIONS_READ = "invitations:read"
PERM_INVITATIONS_REVOKE = "invitations:revoke"

PERM_USERS_READ = "users:read"
PERM_USERS_UPDATE = "users:update"
PERM_USERS_DELETE = "users:delete"

PERM_PATIENTS_CREATE = "patients:create"
PERM_PATIENTS_READ = "patients:read"
PERM_PATIENTS_UPDATE = "patients:update"
PERM_PATIENTS_DELETE = "patients:delete"

PERM_ANALYTICS_READ = "analytics:read"

PERM_APPOINTMENTS_CREATE = "appointments:create"
PERM_APPOINTMENTS_READ = "appointments:read"
PERM_APPOINTMENTS_UPDATE = "appointments:update"
PERM_APPOINTMENTS_DELETE = "appointments:delete"

PERM_AGENTS_READ = "agents:read"
PERM_ALERTS_READ = "alerts:read"
PERM_AGENTS_TRIGGER = "agents:trigger"
PERM_ORG_UPDATE = "org:update"

PERM_CASELOAD_ASSIGN = "caseload:assign"
PERM_CASELOAD_VIEW = "caseload:view" 
PERM_WORKER_STATUS_UPDATE = "workers:status" 
PERM_REPORTS_READ = "reports:read"

PERM_SETTINGS_READ = "settings:read"
PERM_SETTINGS_UPDATE = "settings:update"
PERM_ONBOARDING_COMPLETE = "onboarding:complete"

PERM_DASHBOARD_STATS_READ = "dashboard:stats:read"

# Role Permission Mappings
ROLE_PERMISSIONS = {
    UserRole.ORG_OWNER: ["*"],  # Super admin for the organization
    
    UserRole.ORG_ADMIN: [
        PERM_INVITATIONS_CREATE,
        PERM_INVITATIONS_READ,
        PERM_INVITATIONS_REVOKE,

        PERM_ANALYTICS_READ,
        PERM_DASHBOARD_STATS_READ,
        PERM_REPORTS_READ,

        PERM_USERS_READ,
        PERM_USERS_UPDATE,
        PERM_USERS_DELETE,

        PERM_PATIENTS_CREATE,
        PERM_PATIENTS_READ,
        PERM_PATIENTS_UPDATE,
        PERM_PATIENTS_DELETE,

        PERM_APPOINTMENTS_CREATE,
        PERM_APPOINTMENTS_READ,
        PERM_APPOINTMENTS_UPDATE,
        PERM_APPOINTMENTS_DELETE,

        PERM_AGENTS_READ,
        PERM_ALERTS_READ,
        PERM_AGENTS_TRIGGER,
        PERM_ORG_UPDATE,

        PERM_CASELOAD_ASSIGN,
        PERM_CASELOAD_VIEW,
        PERM_WORKER_STATUS_UPDATE,
    ],
    
    UserRole.DOCTOR: [
        PERM_USERS_READ,
        PERM_REPORTS_READ,
        PERM_DASHBOARD_STATS_READ,

        PERM_PATIENTS_CREATE,
        PERM_PATIENTS_READ,
        PERM_PATIENTS_UPDATE,

        PERM_APPOINTMENTS_CREATE,
        PERM_APPOINTMENTS_READ,
        PERM_APPOINTMENTS_UPDATE,

        PERM_AGENTS_READ,
        PERM_ALERTS_READ,
        PERM_AGENTS_TRIGGER,
    ],
    
    UserRole.NURSE: [
        PERM_DASHBOARD_STATS_READ,
        PERM_PATIENTS_READ,
        PERM_PATIENTS_UPDATE,

        PERM_APPOINTMENTS_READ,
        PERM_APPOINTMENTS_UPDATE,

        PERM_ALERTS_READ,
    ],
    
    UserRole.COORDINATOR: [
        PERM_DASHBOARD_STATS_READ,
        PERM_PATIENTS_READ,

        PERM_APPOINTMENTS_CREATE,
        PERM_APPOINTMENTS_READ,
        PERM_APPOINTMENTS_UPDATE,
        PERM_APPOINTMENTS_DELETE,

        PERM_CASELOAD_ASSIGN,
        PERM_CASELOAD_VIEW,
    ],
}
