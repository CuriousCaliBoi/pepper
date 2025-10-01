import asyncio

from pepper.agent.worker import WorkerAgent

if __name__ == "__main__":

    async def _demo():
        agent = WorkerAgent()
        result = await agent.call(
            "Fetch the 5 most recent emails (show sender, subject, and a one-line preview for each)."
        )
        print(result)


asyncio.run(_demo())
