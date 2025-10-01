import asyncio
import os

from episodic import ContextFilter, ContextStore


async def purge_memory():
    cs = ContextStore(
        endpoint=os.environ.get("CONTEXT_STORE_ENDPOINT"),
        api_key=os.environ.get("CONTEXT_STORE_API_KEY"),
    )
    total_purged = 0
    contexts = await cs.query(ContextFilter(namespaces=["memory-*"], limit=100))
    while len(contexts) > 0:
        for context in contexts:
            await cs.delete(context.id)
        total_purged += len(contexts)
        contexts = await cs.query(ContextFilter(namespaces=["memory-*"], limit=100))
    print(f"Purged {total_purged} contexts")

    await cs.close()


if __name__ == "__main__":
    asyncio.run(purge_memory())
