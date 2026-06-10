import os
import json
import re
from google import genai


SYSTEM_PROMPT = """You are Hermes, an AI assistant for Banksauctions.com helping users find free bank auction properties.

## Database Schema
Table: free_banks_auctions_stage_2_22_38_05_08_06_26
Columns:
- listing_id: Unique ID
- institution: Bank/institution name
- institution_branch: Branch name
- contact_details: Contact info
- auction_type: Type of auction
- borrower_name: Borrower name
- asset_category: Category (e.g. Residential, Commercial, Land)
- asset_type: Type of asset (e.g. Flat, House, Plot, Shop)
- asset_details: Detailed description
- asset_schedule: Schedule info
- asset_address: Full address
- asset_location: Location/area
- city: City name
- reserve_price: Base price in INR
- emd: Earnest Money Deposit in INR
- publication_date: When published
- auction_date_time: Auction start
- auction_end_date_time: Auction end
- application_submission_deadline: Last date to apply
- e_auctionprovider: Auction platform
- documents_available: Available documents

## Your Role
You help users discover auction properties. You should:
1. Ask clarifying questions when you need more info (city, budget, property type)
2. Suggest filters based on what the user mentions
3. Be conversational and quiz-like - ask one question at a time
4. Use the available cities and property types to guide users

## Output Format
You MUST respond with a valid JSON object (no markdown, no code blocks):

For asking a question:
{"action": "ask", "message": "your question here", "filters": {}}

For searching (when you have enough info):
{"action": "search", "message": "summary of what you're searching for", "filters": {"city": "...", "asset_type": "...", "max_reserve_price": 5000000}}

For a general response (greeting, help, etc.):
{"action": "respond", "message": "your response", "filters": {}}
"""


class LLMService:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.0-flash"

    def ask(self, prompt):
        resp = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        return resp.text

    def decide_action(self, user_message, conversation_history, available_cities, available_types):
        cities_sample = ", ".join(available_cities[:20]) if available_cities else "various cities"
        types_sample = ", ".join(available_types[:15]) if available_types else "various types"

        history_text = "\n".join(
            [f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
             for m in conversation_history[-6:]]
        )

        prompt = f"""{SYSTEM_PROMPT}

## Available Data
Cities in database: {cities_sample}
Property types in database: {types_sample}

## Conversation History
{history_text}

## Current User Message
{user_message}

## Task
Respond with a JSON object deciding what to do next.
- If you need more info to search (e.g., city, budget, property type), ask ONE question with action "ask".
- If you have enough info to search, provide filters with action "search".
- For general conversation, use action "respond".
- Use "highlights" key as array of 1-3 key bullet points when responding with results.
- For "search", include ALL relevant filters the user mentioned or implied.
- Use numeric values for price (reserve_price in INR).
"""

        raw = self.ask(prompt)

        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        return {"action": "respond", "message": raw, "filters": {}}

    def generate_property_response(self, properties, total, filters):
        if not properties:
            prompt = f"""The user searched for auction properties but no results were found.
Filters used: {json.dumps(filters)}
Suggest alternative searches or ask what they'd like to change.
Be helpful and concise."""
            return self.ask(prompt)

        listing_text = "\n---\n".join(
            f"Property {i+1}:\n" + "\n".join(f"{k}: {v}" for k, v in p.items() if v)
            for i, p in enumerate(properties[:5])
        )

        prompt = f"""You found {total} auction properties matching the search.
Present the first {min(len(properties), 5)} properties to the user in a friendly, conversational way.
Keep it concise but informative. Suggest they can ask for more details on any property.

Properties:
{listing_text}

Respond naturally as Hermes the auction assistant."""
        return self.ask(prompt)

    def generate_property_detail(self, property_data):
        details = "\n".join(f"{k}: {v}" for k, v in property_data.items() if v)
        prompt = f"""A user wants details on this auction property. Present the full details clearly.

{details}

Respond as Hermes the auction assistant."""
        return self.ask(prompt)

    def suggest_labels(self, conversation_history, existing_labels, available_cities, available_types):
        history_text = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in conversation_history[-10:]
        )
        existing = ", ".join(existing_labels) if existing_labels else "none"

        prompt = f"""You are a CRM label classifier for Banksauctions.com. Analyze this conversation and output ONLY a JSON array of label strings.

Available labels (reuse these if appropriate): {existing}
Cities in DB: {', '.join(available_cities[:15])}
Property types: {', '.join(available_types[:10])}

## Label Categories (use snake_case):
Budget: low_budget, mid_budget, high_budget
Intent: actively_looking, researching, just_browsing, price_inquiry, ready_to_purchase
Lead: new_lead, qualified_lead, hot_lead, warm_lead, cold_lead
Property: apartment, villa, commercial, land, flat, house, plot
Timeline: immediate, within_1_month, within_3_months, long_term_buyer
Other: investor, first_time_buyer, requires_home_loan, nri_client, follow_up_required

## Conversation
{history_text}

## Task
Output a JSON array of label strings that best classify this lead/conversation.
- Include city as label if mentioned (e.g. "mumbai", "delhi")
- Include asset_type if mentioned
- For new conversations with no info: ["new_lead"]
- Max 6 labels. Only include what's evident from the conversation.

Output ONLY the JSON array, nothing else."""
        raw = self.ask(prompt)
        import re
        json_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return ["new_lead"]
