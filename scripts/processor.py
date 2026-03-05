"""
Core transcript processor for Clara Answers pipeline.
Extracts Account Memo and generates Retell Agent Spec from call transcripts.
Supports LLM-powered extraction with rule-based fallback.
"""

import json
import os
import re
import hashlib
import logging
import difflib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

# Add parent to path for imports
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from schemas import AccountMemo, RetellAgentSpec, BusinessHours, EmergencyRoutingRules, \
    EmergencyRouting, NonEmergencyRoutingRules, NonEmergencyDuringHours, \
    NonEmergencyAfterHours, CallTransferRules, KeyVariables, CallTransferProtocol, \
    CallTransferProtocolEntry, FallbackProtocol
from llm_client import LLMClient, extract_json_from_response

logger = logging.getLogger(__name__)

# Base output directory
BASE_DIR = Path(__file__).parent.parent
OUTPUTS_DIR = BASE_DIR / "outputs" / "accounts"


# ─── PROMPTS ─────────────────────────────────────────────────────────

MEMO_EXTRACTION_PROMPT = """You are an expert data extraction assistant. Analyze the following call transcript and extract a structured Account Memo in JSON format.

TRANSCRIPT:
{transcript}

Extract the following fields as a JSON object:
- account_id: Generate from company name (lowercase, underscores, e.g. "bright_smile_dental")
- company_name: Full business name
- business_hours: Object with days (list), start (time), end (time), timezone, exceptions (list of special hours like "Saturday 9 AM - 1 PM")
- office_address: Full address if mentioned, or ""
- services_supported: List of all services mentioned
- emergency_definition: List of what constitutes an emergency for this business
- emergency_routing_rules: Object with during_hours and after_hours, each having primary (target), fallback_chain (list), timeout_seconds, final_fallback
- non_emergency_routing_rules: Object with during_hours (primary, fallback, timeout_seconds, callback_window, message_fields) and after_hours (action, callback_window, additional_info_requested)
- call_transfer_rules: Object with timeout_seconds, max_retries, failure_message
- integration_constraints: List of software/tools mentioned (e.g. "Dentrix for practice management")
- after_hours_flow_summary: Brief summary of after-hours call handling
- office_hours_flow_summary: Brief summary of during-hours call handling
- questions_or_unknowns: List of any information that was unclear or missing from the transcript
- notes: List of any additional relevant details (greetings, special instructions, etc.)

CRITICAL RULES:
1. Output valid JSON only.
2. Do NOT hallucinate or invent information not in the transcript.
3. If information is missing, add it to questions_or_unknowns.
4. Include exact extensions, phone numbers, and names mentioned.
5. Capture greeting/closing phrases in notes.

Respond with ONLY the JSON object, no additional text."""

AGENT_SPEC_PROMPT = """You are an expert at creating Retell AI agent configurations. Given the following Account Memo, generate a complete Retell Agent Draft Spec.

ACCOUNT MEMO:
{memo_json}

Generate a JSON object with:
- agent_name: "{company_name} AI Receptionist"
- voice_style: "professional, warm, and clear"
- system_prompt: A detailed prompt for the AI agent that covers:
  * Opening greeting
  * How to identify caller needs (emergency vs non-emergency)
  * Business hours flow (transfer rules, extensions, timeouts)
  * After-hours flow (emergency protocols, message taking)
  * Transfer protocols (never mention "function calls" to callers, use natural language like "let me connect you")
  * Fallback behavior when transfers fail
  * Closing phrase
  * Any special instructions from notes
- key_variables: timezone, business_hours (formatted string), address, emergency_routing (during/after hours summary)
- tool_invocation_placeholders: List of tool names like ["transfer_call", "take_message", "check_business_hours"]
- call_transfer_protocol: during_hours and after_hours, each a list of steps with step, target, timeout, on_failure
- fallback_protocol: all_lines_busy and technical_failure messages
- version: "v1"

CRITICAL RULES:
1. The system_prompt MUST be detailed and production-ready.
2. NEVER include technical jargon like "function call" or "API" in the system prompt — the caller should never hear these terms.
3. Include business hours flow, after-hours flow, transfer protocols, and fallback logic.
4. Output valid JSON only.

Respond with ONLY the JSON object."""

MEMO_UPDATE_PROMPT = """You are an expert data extraction assistant. You are updating an existing Account Memo with information from an onboarding call transcript.

EXISTING ACCOUNT MEMO:
{existing_memo}

ONBOARDING TRANSCRIPT:
{transcript}

Update the Account Memo with any changes, additions, or corrections from the onboarding call.

RULES:
1. If new information contradicts old information, use the NEW information.
2. If new items are added (services, emergency types, etc.), ADD them to the existing lists.
3. If items are removed, REMOVE them.
4. Preserve all fields from the original memo that weren't changed.
5. Output the COMPLETE updated memo as JSON.
6. Add any newly unclear items to questions_or_unknowns.

Respond with ONLY the complete updated JSON object."""


# ─── RULE-BASED EXTRACTION ──────────────────────────────────────────

def _generate_account_id(company_name: str) -> str:
    """Generate a stable account ID from company name."""
    clean = re.sub(r'[^a-z0-9\s]', '', company_name.lower())
    return '_'.join(clean.split())


def _extract_time_pattern(text: str) -> List[str]:
    """Find time patterns in text."""
    return re.findall(r'\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm|a\.m\.|p\.m\.)', text)


def _extract_address(text: str) -> str:
    """Extract address from transcript text."""
    # Look for common address patterns
    patterns = [
        r'(?:at|address is|located at|we\'re at)\s+([^.]+(?:Suite|Ste|#)\s*\d+[^.]*)',
        r'(\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+(?:Street|St|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Road|Rd|Lane|Ln|Way|Court|Ct))[^.]*\d{5})',
        r'(?:at|address is|located at|we\'re at)\s+([\d].*?(?:TX|AZ|IL|CO|TN|CA|NY|FL|OH|PA|GA|NC|MI|NJ|VA|WA|MA)[\s,]*\d{5})',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            addr = m.group(1).strip().rstrip('.')
            return addr
    return ""


def _extract_business_hours_rule_based(text: str) -> BusinessHours:
    """Extract business hours from transcript using rules."""
    hours = BusinessHours()

    # Timezone detection
    tz_patterns = {
        'Central Time': r'[Cc]entral\s*[Tt]ime',
        'Mountain Standard Time': r'[Mm]ountain\s*[Ss]tandard\s*[Tt]ime|MST',
        'Mountain Time': r'[Mm]ountain\s*[Tt]ime',
        'Eastern Time': r'[Ee]astern\s*[Tt]ime',
        'Pacific Time': r'[Pp]acific\s*[Tt]ime',
    }
    for tz_name, pattern in tz_patterns.items():
        if re.search(pattern, text):
            hours.timezone = tz_name
            break

    # Day patterns
    day_patterns = {
        'Monday through Friday': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'],
        'Monday through Saturday': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'],
        'Monday to Friday': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'],
        'Monday to Saturday': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'],
    }

    for pattern_text, days in day_patterns.items():
        if pattern_text.lower() in text.lower():
            hours.days = days
            # Extract times near this pattern
            idx = text.lower().find(pattern_text.lower())
            context = text[idx:idx+200]
            times = _extract_time_pattern(context)
            if len(times) >= 2:
                hours.start = times[0]
                hours.end = times[1]
            break

    # Saturday exceptions
    sat_match = re.search(r'[Ss]aturday[s]?\s*,?\s*(?:we\'re open\s*)?(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))\s*(?:to|through|-)\s*(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))', text)
    if sat_match:
        hours.exceptions.append(f"Saturday {sat_match.group(1)} - {sat_match.group(2)}")
        if 'Saturday' not in hours.days:
            hours.days.append('Saturday')

    # Sunday exceptions
    sun_match = re.search(r'[Ss]unday[s]?\s*(?:we\'re open\s*)?(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))\s*(?:to|through|-)\s*(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))', text)
    if sun_match:
        hours.exceptions.append(f"Sunday {sun_match.group(1)} - {sun_match.group(2)}")
        if 'Sunday' not in hours.days:
            hours.days.append('Sunday')

    return hours


def _extract_services(text: str) -> List[str]:
    """Extract services list from transcript."""
    services = []

    # Look for service listing sections (after "what services" or similar prompts)
    service_section = re.search(
        r'(?:services?\s+(?:do|does)|what\s+(?:do|does|services))[^.]*?\?\s*(.*?)(?:\[\d|Sarah|Mark|Lisa|Dr\.|Tom|Bill|James)',
        text, re.DOTALL | re.IGNORECASE
    )

    if service_section:
        section_text = service_section.group(1)
        # Split by commas and "and"
        items = re.split(r',\s*(?:and\s+)?|\s+and\s+', section_text)
        for item in items:
            clean = item.strip().rstrip('.').strip()
            if clean and len(clean) > 2 and not clean.startswith('['):
                services.append(clean)
    else:
        # Fallback: look for "We do/offer/provide" patterns
        offer_match = re.search(
            r'(?:[Ww]e\s+(?:do|offer|provide|handle)\s+)(.*?)(?:\.\s*(?:[A-Z]|\[))',
            text, re.DOTALL
        )
        if offer_match:
            items = re.split(r',\s*(?:and\s+)?|\s+and\s+', offer_match.group(1))
            for item in items:
                clean = item.strip().rstrip('.').strip()
                if clean and len(clean) > 2:
                    services.append(clean)

    return services


def _extract_emergencies(text: str) -> List[str]:
    """Extract emergency definitions from transcript."""
    emergencies = []

    # Look for emergency definition sections
    emerg_section = re.search(
        r'(?:emergency|urgent)[^.]*?\?\s*(.*?)(?:\[\d{2}:\d{2}\])',
        text, re.DOTALL | re.IGNORECASE
    )

    if emerg_section:
        section_text = emerg_section.group(1)
        # Split by commas and "and"
        items = re.split(r',\s*(?:and\s+)?|\s+and\s+', section_text)
        for item in items:
            clean = item.strip().rstrip('.').strip()
            # Filter out non-emergency items
            if clean and len(clean) > 5 and not clean.startswith('[') and not clean.startswith('Those'):
                # Remove leading speaker names
                clean = re.sub(r'^(?:Dr\.\s+\w+|Tom|Bill|James|Sarah|Mark|Lisa):\s*', '', clean)
                if clean:
                    emergencies.append(clean)

    return emergencies


def _extract_extensions(text: str) -> Dict[str, str]:
    """Extract phone extensions mentioned in transcript."""
    extensions = {}
    ext_matches = re.findall(r'(?:extension|ext\.?)\s*(\d+)', text, re.IGNORECASE)
    for ext in ext_matches:
        # Find context around the extension
        idx = text.lower().find(f'extension {ext}'.lower())
        if idx == -1:
            idx = text.lower().find(f'ext {ext}'.lower())
        if idx >= 0:
            context = text[max(0, idx-100):idx+50]
            extensions[ext] = context
    return extensions


def rule_based_extract_memo(transcript: str) -> Dict[str, Any]:
    """Extract Account Memo using rule-based approach. Zero-cost guaranteed."""

    # Extract company name from header
    company_match = re.search(r'(?:TRANSCRIPT|CALL).*?—\s*(.+)', transcript)
    company_name = company_match.group(1).strip() if company_match else "Unknown Company"

    account_id = _generate_account_id(company_name)
    address = _extract_address(transcript)
    biz_hours = _extract_business_hours_rule_based(transcript)
    services = _extract_services(transcript)
    emergencies = _extract_emergencies(transcript)

    # Extract routing info
    extensions = _extract_extensions(transcript)

    # Extract greeting
    greeting_match = re.search(r'"([^"]*(?:calling|welcome|thank)[^"]*)"', transcript, re.IGNORECASE)
    greeting = greeting_match.group(1) if greeting_match else ""

    closing_match = re.search(r'"([^"]*(?:wonderful day|take care|choosing|stay|thank)[^"]*)"', transcript, re.IGNORECASE)
    closing = closing_match.group(1) if closing_match else ""

    # Extract callback windows
    callback_match = re.search(r"call\s*back\s*(?:within\s+)?(\d+\s*(?:hour|minute|business hour)s?)", transcript, re.IGNORECASE)
    callback_window = callback_match.group(0) if callback_match else "same business day"

    # Extract timeout
    timeout_match = re.search(r"(?:doesn't|don't|does not)\s*(?:pick up|answer)\s*(?:within|in)\s*(\d+)\s*(?:second|ring)", transcript, re.IGNORECASE)
    timeout_secs = int(timeout_match.group(1)) if timeout_match else 30

    # Integration/software
    software_patterns = [
        r'(?:use|using)\s+([\w]+(?:\s+[\w]+)?)\s+(?:for|as)',
        r'(?:switched?\s+to|migrated?\s+to)\s+([\w]+(?:\s+[\w]+)?)',
    ]
    integrations = []
    for pat in software_patterns:
        matches = re.findall(pat, transcript, re.IGNORECASE)
        for m in matches:
            if m.lower() not in ['a', 'the', 'an', 'our', 'we', 'they', 'it']:
                integrations.append(m)

    # Build emergency routing
    emergency_routing = EmergencyRoutingRules(
        during_hours=EmergencyRouting(
            primary="Front desk / main line",
            fallback_chain=[],
            timeout_seconds=timeout_secs,
            final_fallback="Take message, will callback"
        ),
        after_hours=EmergencyRouting(
            primary="Owner's cell phone",
            fallback_chain=[],
            timeout_seconds=timeout_secs,
            final_fallback="Direct to nearest emergency facility"
        )
    )

    # Build non-emergency routing
    non_emergency = NonEmergencyRoutingRules(
        during_hours=NonEmergencyDuringHours(
            primary="Front desk / reception",
            fallback="Take message",
            timeout_seconds=timeout_secs,
            callback_window=callback_window,
            message_fields=["name", "phone number", "reason for calling"]
        ),
        after_hours=NonEmergencyAfterHours(
            action="take_message",
            callback_window="next business day",
            additional_info_requested=[]
        )
    )

    # Build notes
    notes = []
    if greeting:
        notes.append(f"Opening greeting: {greeting}")
    if closing:
        notes.append(f"Closing phrase: {closing}")

    # Unknowns
    unknowns = []
    if not address:
        unknowns.append("Office address not captured from transcript")
    if not services:
        unknowns.append("Services list not captured from transcript")
    if not biz_hours.timezone:
        unknowns.append("Timezone not specified")

    # Build office hours flow summary
    office_flow = f"During business hours ({biz_hours.start} - {biz_hours.end} {biz_hours.timezone}): "
    office_flow += "Transfer calls to front desk/reception. "
    office_flow += f"If no answer within {timeout_secs} seconds, take message. "
    office_flow += f"Callback within {callback_window}."

    # After hours flow
    after_flow = "After hours: For emergencies, attempt to reach on-call contacts in priority order. "
    after_flow += "For non-emergencies, take detailed message and promise callback next business day."

    memo_data = {
        "account_id": account_id,
        "company_name": company_name,
        "business_hours": biz_hours.model_dump(),
        "office_address": address,
        "services_supported": services,
        "emergency_definition": emergencies,
        "emergency_routing_rules": emergency_routing.model_dump(),
        "non_emergency_routing_rules": non_emergency.model_dump(),
        "call_transfer_rules": CallTransferRules(
            timeout_seconds=timeout_secs,
            max_retries=2,
            failure_message="I'm sorry, I wasn't able to connect you. Let me take your information and someone will call you back shortly."
        ).model_dump(),
        "integration_constraints": integrations,
        "after_hours_flow_summary": after_flow,
        "office_hours_flow_summary": office_flow,
        "questions_or_unknowns": unknowns,
        "notes": notes
    }

    return memo_data


# ─── MAIN PROCESSOR CLASS ──────────────────────────────────────────

class TranscriptProcessor:
    """Main processor for demo and onboarding call transcripts."""

    def __init__(self):
        self.llm = LLMClient()
        self.outputs_dir = OUTPUTS_DIR
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

    def process_demo_call(self, transcript: str, transcript_path: str = "") -> Tuple[Dict, Dict]:
        """
        Pipeline A: Process a demo call transcript.
        Returns (account_memo, agent_spec)
        """
        logger.info(f"Processing demo call: {transcript_path}")

        # Step 1: Extract Account Memo
        memo = self._extract_memo(transcript)

        # Step 2: Generate Retell Agent Spec v1
        spec = self._generate_agent_spec(memo, version="v1")

        # Step 3: Save outputs
        account_id = memo["account_id"]
        self._save_v1(account_id, memo, spec)

        # Step 4: Create task tracker item
        self._create_task_tracker(account_id, memo["company_name"], "demo")

        logger.info(f"Demo call processed successfully for {account_id}")
        return memo, spec

    def process_onboarding_call(self, transcript: str, account_id: str, transcript_path: str = "") -> Tuple[Dict, Dict, str]:
        """
        Pipeline B: Process an onboarding call transcript.
        Returns (updated_memo, updated_spec, changelog)
        """
        logger.info(f"Processing onboarding call for {account_id}: {transcript_path}")

        # Step 1: Load existing v1
        v1_memo, v1_spec = self._load_v1(account_id)
        if not v1_memo:
            raise ValueError(f"No v1 data found for account {account_id}. Run demo call first.")

        # Step 2: Update Account Memo
        updated_memo = self._update_memo(v1_memo, transcript)

        # Step 3: Update Agent Spec v2
        updated_spec = self._generate_agent_spec(updated_memo, version="v2")

        # Step 4: Generate changelog
        changelog = self._generate_changelog(v1_memo, updated_memo, v1_spec, updated_spec)

        # Step 5: Save outputs
        self._save_v2(account_id, updated_memo, updated_spec, changelog)

        logger.info(f"Onboarding call processed successfully for {account_id}")
        return updated_memo, updated_spec, changelog

    def _extract_memo(self, transcript: str) -> Dict[str, Any]:
        """Extract Account Memo from transcript using LLM or fallback."""
        if self.llm.backend != "rule_based":
            try:
                prompt = MEMO_EXTRACTION_PROMPT.format(transcript=transcript)
                response = self.llm.generate(prompt)
                result = extract_json_from_response(response)
                if "_use_rule_based" not in result and "_parse_error" not in result:
                    # Validate and fill missing fields
                    memo = AccountMemo(**result)
                    return memo.model_dump()
            except Exception as e:
                logger.warning(f"LLM extraction failed: {e}. Using rule-based fallback.")

        return rule_based_extract_memo(transcript)

    def _update_memo(self, existing_memo: Dict, transcript: str) -> Dict[str, Any]:
        """Update existing memo with onboarding transcript info."""
        if self.llm.backend != "rule_based":
            try:
                prompt = MEMO_UPDATE_PROMPT.format(
                    existing_memo=json.dumps(existing_memo, indent=2),
                    transcript=transcript
                )
                response = self.llm.generate(prompt)
                result = extract_json_from_response(response)
                if "_use_rule_based" not in result and "_parse_error" not in result:
                    memo = AccountMemo(**result)
                    return memo.model_dump()
            except Exception as e:
                logger.warning(f"LLM update failed: {e}. Using rule-based merge.")

        # Rule-based update: merge new extraction with existing
        new_extraction = rule_based_extract_memo(transcript)
        return self._merge_memos(existing_memo, new_extraction)

    def _merge_memos(self, existing: Dict, new_data: Dict) -> Dict:
        """Merge two memos, preferring new data for conflicts."""
        merged = json.loads(json.dumps(existing))  # Deep copy

        # Keep the original account_id
        merged["account_id"] = existing["account_id"]
        merged["company_name"] = existing["company_name"]

        # Merge lists (add new items)
        list_fields = ["services_supported", "emergency_definition", "integration_constraints", "notes"]
        for field in list_fields:
            existing_items = set(str(x).lower() for x in existing.get(field, []))
            for item in new_data.get(field, []):
                if str(item).lower() not in existing_items:
                    merged.setdefault(field, []).append(item)

        # Update business hours if new data has them
        if new_data.get("business_hours", {}).get("timezone"):
            merged["business_hours"] = new_data["business_hours"]

        # Update address if newly provided
        if new_data.get("office_address") and not existing.get("office_address"):
            merged["office_address"] = new_data["office_address"]

        # Update flow summaries
        for field in ["after_hours_flow_summary", "office_hours_flow_summary"]:
            if new_data.get(field):
                merged[field] = new_data[field]

        # Merge unknowns
        merged["questions_or_unknowns"] = list(set(
            existing.get("questions_or_unknowns", []) + new_data.get("questions_or_unknowns", [])
        ))

        return merged

    def _generate_agent_spec(self, memo: Dict, version: str = "v1") -> Dict[str, Any]:
        """Generate Retell Agent Spec from Account Memo."""
        company_name = memo.get("company_name", "Unknown")

        if self.llm.backend != "rule_based":
            try:
                prompt = AGENT_SPEC_PROMPT.format(
                    memo_json=json.dumps(memo, indent=2),
                    company_name=company_name
                )
                response = self.llm.generate(prompt)
                result = extract_json_from_response(response)
                if "_use_rule_based" not in result and "_parse_error" not in result:
                    result["version"] = version
                    spec = RetellAgentSpec(**result)
                    return spec.model_dump()
            except Exception as e:
                logger.warning(f"LLM spec generation failed: {e}. Using rule-based.")

        return self._rule_based_generate_spec(memo, version)

    def _rule_based_generate_spec(self, memo: Dict, version: str) -> Dict[str, Any]:
        """Generate agent spec using rules. Zero-cost guaranteed."""
        company_name = memo.get("company_name", "Unknown")
        biz_hours = memo.get("business_hours", {})
        address = memo.get("office_address", "")
        services = memo.get("services_supported", [])
        emergencies = memo.get("emergency_definition", [])
        notes = memo.get("notes", [])

        # Build greeting from notes
        greeting = "Thank you for calling. How may I help you today?"
        closing = "Thank you for calling. Have a great day!"
        for note in notes:
            if "greeting" in note.lower():
                g = re.search(r':\s*(.+)', note)
                if g:
                    greeting = g.group(1).strip()
            if "closing" in note.lower():
                c = re.search(r':\s*(.+)', note)
                if c:
                    closing = c.group(1).strip()

        # Build hours string
        days = biz_hours.get("days", [])
        hours_str = f"{', '.join(days)}: {biz_hours.get('start', '9 AM')} - {biz_hours.get('end', '5 PM')} {biz_hours.get('timezone', '')}"
        exceptions = biz_hours.get("exceptions", [])
        if exceptions:
            hours_str += ". " + ". ".join(exceptions)

        # Build system prompt
        system_prompt = f"""You are the AI phone receptionist for {company_name}.

GREETING: Always begin every call with: "{greeting}"

COMPANY INFORMATION:
- Business: {company_name}
- Address: {address if address else "Not specified"}
- Business Hours: {hours_str}
- Services: {', '.join(services) if services else 'General services'}

CALL HANDLING PROTOCOL:

1. IDENTIFY CALLER NEEDS:
   - Listen carefully to determine if the call is an emergency or routine matter
   - Ask clarifying questions if needed: "Could you tell me more about what you're experiencing?"

2. EMERGENCY SITUATIONS:
   The following are considered emergencies:
{chr(10).join(f'   - {e}' for e in emergencies) if emergencies else '   - Life-threatening situations'}

   DURING BUSINESS HOURS (Emergency):
   - Say: "I understand this is urgent. Let me connect you with someone who can help right away."
   - Transfer to the primary contact immediately
   - If no answer within the timeout, try the backup contacts in order
   - If all contacts unavailable, take detailed information and assure a callback ASAP

   AFTER HOURS (Emergency):
   - Say: "I understand this is urgent. Our office is currently closed, but let me reach our on-call team."
   - Attempt to reach emergency contacts in priority order
   - If no one is available, provide appropriate emergency guidance and take a message

3. NON-EMERGENCY CALLS:
   DURING BUSINESS HOURS:
   - Say: "I'd be happy to help. Let me connect you with our team."
   - Transfer to the front desk / primary contact
   - If no answer, take a message: caller name, phone number, and reason for calling
   - Inform them of the expected callback window

   AFTER HOURS:
   - Say: "Our office is currently closed. I'd be happy to take a message."
   - Collect: caller name, phone number, reason for calling
   - Inform them when to expect a callback

4. MESSAGE TAKING:
   Always collect:
   - Caller's full name
   - Best callback number
   - Reason for calling
   - Any additional relevant details

5. TRANSFER PROTOCOL:
   - When transferring: "Please hold while I connect you."
   - If transfer fails: "I apologize, but I'm unable to connect you at the moment. Let me take your information so we can call you back."
   - Never mention technical terms — use natural, conversational language

CLOSING: Always end with: "{closing}"

IMPORTANT RULES:
- Be warm, professional, and empathetic at all times
- Never rush the caller
- Never mention internal systems, technical processes, or backend operations
- If unsure about something, take a message rather than guessing
- Prioritize caller safety in emergency situations"""

        # Build transfer protocol
        emerg_routing = memo.get("emergency_routing_rules", {})
        during_hours_routing = emerg_routing.get("during_hours", {})
        after_hours_routing = emerg_routing.get("after_hours", {})

        transfer_protocol = CallTransferProtocol(
            during_hours=[
                CallTransferProtocolEntry(
                    step="1",
                    target=during_hours_routing.get("primary", "Front desk"),
                    timeout=f"{during_hours_routing.get('timeout_seconds', 30)} seconds",
                    on_failure="Try fallback contacts"
                ),
                CallTransferProtocolEntry(
                    step="2",
                    target="Fallback contacts in order",
                    timeout=f"{during_hours_routing.get('timeout_seconds', 30)} seconds each",
                    on_failure="Take message, promise callback"
                )
            ],
            after_hours=[
                CallTransferProtocolEntry(
                    step="1",
                    target=after_hours_routing.get("primary", "On-call contact"),
                    timeout=f"{after_hours_routing.get('timeout_seconds', 30)} seconds",
                    on_failure="Try fallback contacts"
                ),
                CallTransferProtocolEntry(
                    step="2",
                    target=after_hours_routing.get("final_fallback", "Take message"),
                    timeout="N/A",
                    on_failure="Take message, provide emergency guidance"
                )
            ]
        )

        spec = RetellAgentSpec(
            agent_name=f"{company_name} AI Receptionist",
            voice_style="professional, warm, and clear",
            system_prompt=system_prompt,
            key_variables=KeyVariables(
                timezone=biz_hours.get("timezone", ""),
                business_hours=hours_str,
                address=address,
                emergency_routing={
                    "during_hours": during_hours_routing,
                    "after_hours": after_hours_routing
                }
            ),
            tool_invocation_placeholders=[
                "transfer_call",
                "take_message",
                "check_business_hours",
                "send_notification",
                "log_call"
            ],
            call_transfer_protocol=transfer_protocol,
            fallback_protocol=FallbackProtocol(
                all_lines_busy="I apologize, but all our lines are currently busy. Let me take your name and number, and someone will return your call as soon as possible.",
                technical_failure="I'm sorry, I'm experiencing a temporary issue. Please try calling back in a few minutes, or leave your name and number and we'll reach out to you."
            ),
            version=version
        )

        return spec.model_dump()

    def _generate_changelog(self, v1_memo: Dict, v2_memo: Dict,
                            v1_spec: Dict, v2_spec: Dict) -> str:
        """Generate a markdown changelog between v1 and v2."""
        lines = [
            f"# Changelog: {v1_memo.get('company_name', 'Unknown')}",
            f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Account ID**: {v1_memo.get('account_id', '')}",
            "",
            "## Account Memo Changes",
            ""
        ]

        # Compare specific fields
        fields_to_compare = [
            ("business_hours", "Business Hours"),
            ("office_address", "Office Address"),
            ("services_supported", "Services Supported"),
            ("emergency_definition", "Emergency Definitions"),
            ("emergency_routing_rules", "Emergency Routing"),
            ("non_emergency_routing_rules", "Non-Emergency Routing"),
            ("call_transfer_rules", "Call Transfer Rules"),
            ("integration_constraints", "Integrations"),
            ("after_hours_flow_summary", "After-Hours Flow"),
            ("office_hours_flow_summary", "Office Hours Flow"),
            ("notes", "Notes"),
        ]

        changes_found = False
        for field, label in fields_to_compare:
            v1_val = v1_memo.get(field)
            v2_val = v2_memo.get(field)

            if v1_val != v2_val:
                changes_found = True
                lines.append(f"### {label}")

                if isinstance(v1_val, list) and isinstance(v2_val, list):
                    v1_set = set(str(x) for x in v1_val)
                    v2_set = set(str(x) for x in v2_val)

                    added = v2_set - v1_set
                    removed = v1_set - v2_set

                    if added:
                        lines.append("**Added:**")
                        for item in sorted(added):
                            lines.append(f"- ✅ {item}")
                    if removed:
                        lines.append("**Removed:**")
                        for item in sorted(removed):
                            lines.append(f"- ❌ {item}")
                    lines.append("")
                elif isinstance(v1_val, dict) and isinstance(v2_val, dict):
                    v1_str = json.dumps(v1_val, indent=2, sort_keys=True)
                    v2_str = json.dumps(v2_val, indent=2, sort_keys=True)
                    diff = list(difflib.unified_diff(
                        v1_str.splitlines(),
                        v2_str.splitlines(),
                        lineterm="",
                        fromfile="v1",
                        tofile="v2"
                    ))
                    if diff:
                        lines.append("```diff")
                        lines.extend(diff)
                        lines.append("```")
                        lines.append("")
                else:
                    lines.append(f"- **v1**: {v1_val}")
                    lines.append(f"- **v2**: {v2_val}")
                    lines.append("")

        if not changes_found:
            lines.append("_No changes detected in memo fields._")
            lines.append("")

        # System prompt diff
        lines.append("## Agent Spec Changes")
        lines.append("")

        v1_prompt = v1_spec.get("system_prompt", "")
        v2_prompt = v2_spec.get("system_prompt", "")

        if v1_prompt != v2_prompt:
            lines.append("### System Prompt")
            diff = list(difflib.unified_diff(
                v1_prompt.splitlines(),
                v2_prompt.splitlines(),
                lineterm="",
                fromfile="v1",
                tofile="v2"
            ))
            if diff:
                lines.append("```diff")
                lines.extend(diff)
                lines.append("```")
        else:
            lines.append("_No changes in system prompt._")

        lines.append("")
        lines.append("---")
        lines.append(f"*Version upgraded from {v1_spec.get('version', 'v1')} → {v2_spec.get('version', 'v2')}*")

        return "\n".join(lines)

    def _save_v1(self, account_id: str, memo: Dict, spec: Dict):
        """Save v1 outputs."""
        account_dir = self.outputs_dir / account_id / "v1"
        account_dir.mkdir(parents=True, exist_ok=True)

        with open(account_dir / "memo.json", "w", encoding="utf-8") as f:
            json.dump(memo, f, indent=2, ensure_ascii=False)

        with open(account_dir / "agent_spec.json", "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved v1 for {account_id}")

    def _save_v2(self, account_id: str, memo: Dict, spec: Dict, changelog: str):
        """Save v2 outputs and changelog."""
        v2_dir = self.outputs_dir / account_id / "v2"
        v2_dir.mkdir(parents=True, exist_ok=True)

        with open(v2_dir / "memo.json", "w", encoding="utf-8") as f:
            json.dump(memo, f, indent=2, ensure_ascii=False)

        with open(v2_dir / "agent_spec.json", "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2, ensure_ascii=False)

        changelog_path = self.outputs_dir / account_id / "changelog.md"
        with open(changelog_path, "w", encoding="utf-8") as f:
            f.write(changelog)

        logger.info(f"Saved v2 and changelog for {account_id}")

    def _load_v1(self, account_id: str) -> Tuple[Optional[Dict], Optional[Dict]]:
        """Load existing v1 data for an account."""
        v1_dir = self.outputs_dir / account_id / "v1"

        memo = None
        spec = None

        memo_path = v1_dir / "memo.json"
        spec_path = v1_dir / "agent_spec.json"

        if memo_path.exists():
            with open(memo_path, "r", encoding="utf-8") as f:
                memo = json.load(f)

        if spec_path.exists():
            with open(spec_path, "r", encoding="utf-8") as f:
                spec = json.load(f)

        return memo, spec

    def _create_task_tracker(self, account_id: str, company_name: str, phase: str):
        """Create a mock task tracker entry (saved as JSON file)."""
        tracker_dir = self.outputs_dir / account_id
        tracker_dir.mkdir(parents=True, exist_ok=True)

        task = {
            "task_id": hashlib.md5(f"{account_id}_{phase}".encode()).hexdigest()[:8],
            "account_id": account_id,
            "company_name": company_name,
            "phase": phase,
            "status": "completed",
            "created_at": datetime.now().isoformat(),
            "steps_completed": [
                "transcript_received",
                "memo_extracted",
                "agent_spec_generated",
                "artifacts_saved"
            ]
        }

        with open(tracker_dir / f"task_{phase}.json", "w", encoding="utf-8") as f:
            json.dump(task, f, indent=2)


# ─── TRANSCRIPT MAPPING ─────────────────────────────────────────────

# Maps demo transcripts to their onboarding counterparts
TRANSCRIPT_PAIRS = {
    "demo_call_01_dental": ("onboarding_call_01_dental", "bright_smile_dental"),
    "demo_call_02_plumbing": ("onboarding_call_02_plumbing", "quickfix_plumbing_co"),
    "demo_call_03_legal": ("onboarding_call_03_legal", "hartfield_associates_law_firm"),
    "demo_call_04_veterinary": ("onboarding_call_04_veterinary", "pawsitive_care_veterinary_clinic"),
    "demo_call_05_hvac": ("onboarding_call_05_hvac", "summit_heating_cooling"),
}


def get_account_id_from_demo(demo_filename: str) -> str:
    """Get the expected account ID from a demo transcript filename."""
    base = Path(demo_filename).stem
    if base in TRANSCRIPT_PAIRS:
        return TRANSCRIPT_PAIRS[base][1]
    return ""


def get_onboarding_for_demo(demo_filename: str) -> str:
    """Get the onboarding transcript filename that pairs with a demo."""
    base = Path(demo_filename).stem
    if base in TRANSCRIPT_PAIRS:
        return TRANSCRIPT_PAIRS[base][0]
    return ""
