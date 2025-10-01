import logging
import os

from fastmcp import FastMCP

from episodic import ContextStore
from pepper.services.user_profile_service import UserProfileService

mcp = FastMCP("user-profile-mcp-server")

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize context store with environment variables or defaults
CONTEXT_STORE_ENDPOINT = os.environ.get(
    "CONTEXT_STORE_ENDPOINT", "http://localhost:8000"
)
CONTEXT_STORE_API_KEY = os.environ.get("CONTEXT_STORE_API_KEY", "your-api-key-here")


@mcp.tool()
async def update_user_profile(field_name: str, field_value: str) -> dict:
    """Update a specific field in the user profile.
    
    This tool updates a single field in the user's profile. Only one field
    can be updated at a time to ensure atomic operations and clear tracking
    of changes.
    
    Args:
        field_name: The field to update. Must be one of:
                   - 'full_name': Full name with preferred name (e.g., "John Doe (Preferred: Johnny)")
                   - 'current_address': Complete address including unit number
                   - 'work_experience': Work history formatted as string
                   - 'education': Education background  
                   - 'contact_info': Email addresses and phone
                   - 'additional_notes': Other relevant details
        field_value: The new value for the field (must be a non-empty string)
    
    Returns:
        dict: The complete updated profile with all fields
        
    Examples:
        - update_user_profile("full_name", "Jane Smith (Preferred: Janie)")
        - update_user_profile("current_address", "123 Main St, Apt 4B, New York, NY 10001")
        - update_user_profile("work_experience", "Google (Software Engineer, 2020-2023) - Worked on search infrastructure")
    
    Raises:
        Error if field_name is invalid or update fails
    """
    try:
        context_store = ContextStore(
            endpoint=CONTEXT_STORE_ENDPOINT, api_key=CONTEXT_STORE_API_KEY
        )
        
        service = UserProfileService(context_store)
        
        # Validate and update the field
        updated_profile = await service.update_profile_field(field_name, field_value)
        
        return {
            "status": "success",
            "message": f"Successfully updated '{field_name}', make sure this is what you wanted, if not, please try again until you get it correct.",
            "updated_profile": updated_profile
        }
    except ValueError as e:
        return {
            "status": "error", 
            "error": str(e),
            "valid_fields": [
                "full_name", "current_address", "work_experience",
                "education", "contact_info", "additional_notes"
            ]
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Failed to update user profile: {str(e)}"
        }


@mcp.tool()
async def get_user_profile() -> dict:
    """Get the current user profile information.

    This tool retrieves the user's profile containing:
    - Full name and preferred names
    - Current address (including apartment/unit number)
    - Complete work experience (all companies, roles, periods)
    - Education background
    - Contact information
    - Additional relevant details

    The profile is automatically maintained and updated weekly.

    Returns:
        dict: The user profile data with fields:
            - full_name: Full name with preferred name if any
            - current_address: Complete address including unit number
            - work_experience: All work experiences formatted as string
            - education: Education background
            - contact_info: Email addresses and phone
            - additional_notes: Other relevant details

        Returns error message if profile not found or retrieval fails.
    """
    try:
        context_store = ContextStore(
            endpoint=CONTEXT_STORE_ENDPOINT, api_key=CONTEXT_STORE_API_KEY
        )

        service = UserProfileService(context_store)
        profile_data = await service.get_profile_data()
        if profile_data:
            return profile_data
        return await service._call_builder()
    except Exception as e:
        return {"error": f"Failed to retrieve user profile: {str(e)}"}

if __name__ == "__main__":
    mcp.run(transport="stdio")
