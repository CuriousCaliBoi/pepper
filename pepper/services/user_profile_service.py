from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional, Protocol

from episodic import Context, ContextStore
from pepper.constants import TOOL_DIR

class ProfileBuilderProtocol(Protocol):
    async def build(self) -> dict: ...


BuildProfileFn = Callable[[], Awaitable[dict]]

class UserProfileService:
    """
    Profile domain service. Responsible for reading/writing profile data to ContextStore,
    keeping history, and constructing new profiles via a pluggable builder strategy.
    """

    def __init__(
        self,
        context_store: ContextStore,
        *,
        profile_ttl_seconds: int = 7 * 24 * 60 * 60,
        history_ttl_seconds: int = 30 * 24 * 60 * 60,
    ) -> None:
        self.context_store = context_store
        self.profile_ttl_seconds = profile_ttl_seconds
        self.history_ttl_seconds = history_ttl_seconds

    async def get_profile_context(self) -> Optional[Context]:
        try:
            return await self.context_store.get(context_id="user_profile")
        except Exception:
            return None

    async def get_profile_data(self) -> Optional[dict]:
        profile_context = await self.get_profile_context()
        if profile_context is None:
            return None
        if isinstance(profile_context, Context):
            return profile_context.data
        # Fallback if a dict-like object is returned
        if isinstance(profile_context, dict):
            return profile_context.get("data")
        return None

    async def save_profile(self, profile_data: dict) -> None:
        await self.context_store.store(
            context_id="user_profile",
            data=profile_data,
            namespace="user_profile",
            context_type="user_profile",
            ttl=self.profile_ttl_seconds,
        )

    async def save_history(self, profile_context: Context) -> None:
        # Extract raw data
        if isinstance(profile_context, Context):
            data = profile_context.data
        elif isinstance(profile_context, dict):
            data = profile_context.get("data", {})
        else:
            data = {}

        await self.context_store.store(
            context_id=f"user_profile_history_{datetime.now().isoformat()}",
            data=data,
            namespace="user_profile_history",
            context_type="user_profile_history",
            ttl=self.history_ttl_seconds,
        )

    async def refresh(self) -> dict:
        profile = await self._call_builder()
        await self.save_profile(profile)
        return profile

    async def update_profile_field(self, field_name: str, field_value: str) -> dict:
        """Update a single field in the user profile.
        
        Args:
            field_name: The name of the field to update. Must be one of:
                       'full_name', 'current_address', 'work_experience',
                       'education', 'contact_info', 'additional_notes'
            field_value: The new value for the field (as a string)
        
        Returns:
            dict: The updated profile data
            
        Raises:
            ValueError: If field_name is not valid or field_value is invalid
        """
        # Define valid fields
        valid_fields = {
            'full_name', 'current_address', 'work_experience',
            'education', 'contact_info', 'additional_notes'
        }
        
        if field_name not in valid_fields:
            raise ValueError(f"Invalid field name '{field_name}'. Must be one of: {valid_fields}")
        
        # Validate field value
        if not field_value or not isinstance(field_value, str):
            raise ValueError(f"Field value must be a non-empty string, got {field_value}. Note it should be one of the following: 'full_name', 'current_address', 'work_experience', 'education', 'contact_info', 'additional_notes'. Try again.")
        
        # Get current profile
        current_profile = await self.get_profile_data()
        if current_profile is None:
            # If no profile exists, create a new one with just this field
            current_profile = {field: "" for field in valid_fields}
        
        # Save current profile to history before updating
        if current_profile and any(current_profile.values()):
            # Create a Context-like object for history
            profile_context = await self.get_profile_context()
            if profile_context:
                await self.save_history(profile_context)
        
        # Update the specific field
        current_profile[field_name] = field_value
        
        # Save the updated profile
        await self.save_profile(current_profile)
        
        return current_profile

    async def _call_builder(self) -> dict:
        # Support either a strategy with build() or a bare async callable
        from pepper.agent.workflow import WorkflowAgent
        task = """Find comprehensive information about me including:

1. My full name (first name, last name, any preferred names)
   - Find out the email profile that contains my full name
   - I'll have sent and received emails with this profile

2. Complete work experience including:
   - ALL companies I've worked at
   - Specific roles/titles at each company
   - Internships, full-time positions, and research positions
   - Time periods if available
   - Key projects or responsibilities
   - Industries and locations

3. Detailed residence information:
   - Current address including apartment/unit number
   - Building/complex name
   - City, state, country
   - Any previous addresses if mentioned
   
4. Additional relevant information:
   - Education background
   - Research interests or publications
   - Contact information
   - Immigration status if relevant
   - Any other notable personal or professional details

Search thoroughly through emails, including lease documents, offer letters, onboarding materials, 
and any correspondence that might contain these details. If for some part, you can't find the information,
try again with a different approach, if it still doesn't work, leave it blank.

For employment information, include companies that I've signed employment contracts with. And for those that
you're not sure, indicate it's not confirmed.

For name, if the name is not clear, try explicitly ask the agent to find it by listing the top 20 emails,
and check the sender and receiver name to find it, every email should have one of the sender and receiver being the user.
"""
        output_format = """
Return a clean JSON object with these string fields:
{
    "full_name": "First Last (Preferred: nickname if any)",
    "current_address": "Full address including apartment/unit number, building name, city, state, country",
    "work_experience": "Comprehensive list formatted as: Company (Role, Type, Period, Location) - Description.",
    "education": "Institution(s), degree(s), field of study, notable achievements",
    "contact_info": "Email addresses, phone if available",
    "additional_notes": "Any other relevant personal or professional details"
}
"""
        agent = WorkflowAgent(config_path=TOOL_DIR / "profile_building_tools.yaml")
        profile = await agent.execute(task, output_format)
        try:
            return json.loads(profile)
        except Exception:
            return profile
