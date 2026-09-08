import asyncio
from app.services.llm_service import LLMService

async def test_llm_service():
    llm = LLMService()
    print("Testing LLMService.complete()...")
    res = await llm.complete(
        system="You are a GTM AI assistant.",
        user="Return a JSON with key 'greeting' and value 'Hello from Gemini!'",
        response_format={"greeting": "string"}
    )
    print("Result complete():", res)
    
    print("\nTesting LLMService.complete_raw()...")
    raw = await llm.complete_raw(
        system_or_prompt="You are an expert sales writer.",
        user_prompt="Write a 1-sentence sales hook for a B2B SaaS platform."
    )
    print("Result complete_raw():", raw)

if __name__ == "__main__":
    asyncio.run(test_llm_service())
