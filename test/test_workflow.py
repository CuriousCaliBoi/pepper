import asyncio

from pepper.agent.workflow import WorkflowAgent

if __name__ == "__main__":

    async def _demo():
        # Example 1: Daily briefing workflow
        task = """Find comprehensive information about me including:

1. My full name (first name, last name, any preferred names)

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
and any correspondence that might contain these details. Look for specific apartment numbers, 
unit numbers, or suite numbers in lease agreements or building communications.
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
        agent = WorkflowAgent()
        result = await agent.execute(task, output_format)
        print(result)

    asyncio.run(_demo())
