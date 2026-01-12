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

PERM_APPOINTMENTS_CREATE = "appointments:create"
PERM_APPOINTMENTS_READ = "appointments:read"
PERM_APPOINTMENTS_UPDATE = "appointments:update"
PERM_APPOINTMENTS_DELETE = "appointments:delete"

# Role Permission Mappings
ROLE_PERMISSIONS = {
    UserRole.ORG_OWNER: ["*"],  # Super admin for the organization
    
    UserRole.ORG_ADMIN: [
        # Invitations
        PERM_INVITATIONS_CREATE,
        PERM_INVITATIONS_READ,
        PERM_INVITATIONS_REVOKE,
        
        # Users
        PERM_USERS_READ,
        PERM_USERS_UPDATE,
        PERM_USERS_DELETE,
        
        # Patients
        PERM_PATIENTS_CREATE,
        PERM_PATIENTS_READ,
        PERM_PATIENTS_UPDATE,
        PERM_PATIENTS_DELETE,
        
        # Appointments
        PERM_APPOINTMENTS_CREATE,
        PERM_APPOINTMENTS_READ,
        PERM_APPOINTMENTS_UPDATE,
        PERM_APPOINTMENTS_DELETE,
    ],
    
    UserRole.DOCTOR: [
        # Users
        PERM_USERS_READ,
        
        # Patients
        PERM_PATIENTS_CREATE,
        PERM_PATIENTS_READ,
        PERM_PATIENTS_UPDATE,
        
        # Appointments
        PERM_APPOINTMENTS_CREATE,
        PERM_APPOINTMENTS_READ,
        PERM_APPOINTMENTS_UPDATE,
    ],
    
    UserRole.NURSE: [
        # Patients
        PERM_PATIENTS_READ,
        PERM_PATIENTS_UPDATE,
        
        # Appointments
        PERM_APPOINTMENTS_READ,
        PERM_APPOINTMENTS_UPDATE,
    ],
    
    UserRole.COORDINATOR: [
        # Patients
        PERM_PATIENTS_READ,
        
        # Appointments
        PERM_APPOINTMENTS_CREATE,
        PERM_APPOINTMENTS_READ,
        PERM_APPOINTMENTS_UPDATE,
        PERM_APPOINTMENTS_DELETE,
    ],
}
