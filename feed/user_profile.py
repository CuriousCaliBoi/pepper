import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from episodic import ContextStore
from pepper.services.user_profile_service import UserProfileService


class UserProfileFeed:
    """
    Lightweight weekly scheduler for the user profile.
    Creates the profile if missing and refreshes it on a cron.
    """

    def __init__(self, context_store: ContextStore, schedule_config: dict = None):
        self.logger = logging.getLogger(__name__)

        # Domain service (storage + pluggable builder)
        self.service = UserProfileService(context_store)

        # Scheduler setup
        self.scheduler = AsyncIOScheduler()
        self.schedule_config = schedule_config or {
            "day_of_week": "mon",  # Every Monday
            "hour": 9,  # At 9 AM
            "minute": 0,  # At :00
        }

    async def start(self):
        # Ensure profile exists once at startup, then schedule weekly refreshes
        profile = await self.service.get_profile_data()
        if profile is None:
            await self.service.refresh()
            profile = await self.service.get_profile_data()
        self.start_scheduled_updates()
        return profile

    def start_scheduled_updates(self):
        """Start the scheduler for periodic profile updates"""
        # Add the job with cron trigger
        self.scheduler.add_job(
            self.update_user_profile,
            CronTrigger(**self.schedule_config),
            id="weekly_profile_update",
            replace_existing=True,
            name="Weekly User Profile Update",
        )

        # Start the scheduler if not already running
        if not self.scheduler.running:
            self.scheduler.start()
            self.logger.info(
                f"Started profile update scheduler: {self.schedule_config}"
            )

    async def update_user_profile(self):
        """Update the user profile with latest information"""
        self.logger.info(f"Starting scheduled profile update at {datetime.now()}")

        try:
            current_context = await self.service.get_profile_context()
            new_profile = await self.service.refresh()
            if current_context:
                self.logger.info("Profile updated successfully")
                await self.service.save_history(current_context)
            return new_profile
        except Exception as e:
            self.logger.error(f"Error updating user profile: {e}")
            raise

    def stop_scheduled_updates(self):
        """Stop the scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            self.logger.info("Stopped profile update scheduler")


if __name__ == "__main__":
    import os

    endpoint = os.environ.get("CONTEXT_STORE_ENDPOINT", "http://localhost:8000")
    api_key = os.environ.get("CONTEXT_STORE_API_KEY", "your-api-key-here")

    async def main():
        # Configure logging
        logging.basicConfig(level=logging.INFO)

        context_store = ContextStore(endpoint=endpoint, api_key=api_key)

        # Example 1: Default schedule (Every Monday at 9 AM)
        user_profile_feed = UserProfileFeed(context_store)

        # Start the feed (will create profile if needed and start scheduler)
        profile = await user_profile_feed.start()
        print(f"[USER PROFILE FEED] Your user profile is initialized.")

        # Keep the program running to allow scheduled updates
        try:
            # Run forever
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            print("\nShutting down...")
            user_profile_feed.stop_scheduled_updates()

    asyncio.run(main())
