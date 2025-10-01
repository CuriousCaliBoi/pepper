import asyncio
import os
import time

from composio import Composio
from composio.core.models.base import allow_tracking

from episodic import ContextStore
from pepper.constants import COMPOSIO_USER_ID

allow_tracking.set(False)

COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY")
CONTEXT_STORE_ENDPOINT = os.environ.get("CONTEXT_STORE_ENDPOINT")
CONTEXT_STORE_API_KEY = os.environ.get("CONTEXT_STORE_API_KEY")


def get_or_create_gmail_auth_config_id(composio_client: Composio) -> str:
    """
    Returns the latest Gmail auth_config_id if one exists; otherwise creates one
    using Composio managed auth and returns its id.
    """
    existing = composio_client.auth_configs.list(toolkit_slug="gmail")
    if existing.items:
        latest = max(existing.items, key=lambda c: c.created_at or "")
        return latest.id

    created = composio_client.auth_configs.create(
        toolkit="gmail",
        options={
            "type": "use_composio_managed_auth",
        },
    )
    return created.id


def ensure_gmail_connected_account_id(composio_client: Composio, user_id: str) -> str:
    """
    Return an ACTIVE Gmail connected_account id for the given user if it exists;
    otherwise initiate OAuth and wait until the connection is active.
    """
    connected_accounts = composio_client.connected_accounts.list(
        user_ids=[user_id],
        toolkit_slugs=["GMAIL"],
    )
    for account in connected_accounts.items:
        if account.status == "ACTIVE":
            return account.id

    auth_config_id = get_or_create_gmail_auth_config_id(composio_client)
    connection_request = composio_client.connected_accounts.initiate(
        user_id=user_id,
        auth_config_id=auth_config_id,
    )
    print(f"Please authorize Gmail by visiting: {connection_request.redirect_url}")
    connected_account = connection_request.wait_for_connection()
    return connected_account.id


composio = Composio(api_key=COMPOSIO_API_KEY)

auth_config_id = get_or_create_gmail_auth_config_id(composio)

connected_account_id = ensure_gmail_connected_account_id(composio, COMPOSIO_USER_ID)

# Create a new trigger for the user's connected account
trigger = composio.triggers.create(
    user_id=COMPOSIO_USER_ID,
    slug="GMAIL_NEW_GMAIL_MESSAGE",
    trigger_config={"labelIds": "INBOX", "userId": "me", "interval": 1},
)
print(f"✅ Trigger subscribed successfully.")

subscription = composio.triggers.subscribe()


@subscription.handle(trigger_id=trigger.trigger_id)
def handle_gmail_event(data):
    async def _store():
        context_store = ContextStore(
            endpoint=CONTEXT_STORE_ENDPOINT,
            api_key=CONTEXT_STORE_API_KEY,
        )
        await context_store.store(
            context_id=f"composio_gmail_event_{time.time()}",
            data=data,
            text="New Gmail event",
            namespace="composio",
            context_type="composio_gmail_event",
        )
        await context_store.close()

    asyncio.run(_store())


# Keep process alive to receive trigger events
print("[email_service] Waiting for Gmail trigger events...")
subscription.wait_forever()
