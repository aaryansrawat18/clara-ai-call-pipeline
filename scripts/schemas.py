"""
Data schemas for Clara Answers automation pipeline.
Pydantic models for Account Memo and Retell Agent Draft Spec.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class BusinessHours(BaseModel):
    days: List[str] = Field(default_factory=list, description="Days of operation, e.g. ['Monday','Tuesday',...]")
    start: str = Field(default="", description="Opening time, e.g. '8:00 AM'")
    end: str = Field(default="", description="Closing time, e.g. '5:00 PM'")
    timezone: str = Field(default="", description="Timezone, e.g. 'Central Time'")
    exceptions: List[str] = Field(default_factory=list, description="Special hours, e.g. 'Saturday 9 AM - 1 PM'")


class RoutingStep(BaseModel):
    target: str = Field(default="", description="Who to call/transfer to")
    timeout_seconds: int = Field(default=30)
    notes: str = Field(default="")


class EmergencyRouting(BaseModel):
    primary: str = Field(default="")
    fallback_chain: List[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=30)
    final_fallback: str = Field(default="")


class EmergencyRoutingRules(BaseModel):
    during_hours: EmergencyRouting = Field(default_factory=EmergencyRouting)
    after_hours: EmergencyRouting = Field(default_factory=EmergencyRouting)


class NonEmergencyDuringHours(BaseModel):
    primary: str = Field(default="")
    fallback: str = Field(default="")
    timeout_seconds: int = Field(default=45)
    callback_window: str = Field(default="")
    message_fields: List[str] = Field(default_factory=lambda: ["name", "phone", "reason"])


class NonEmergencyAfterHours(BaseModel):
    action: str = Field(default="take_message")
    callback_window: str = Field(default="")
    additional_info_requested: List[str] = Field(default_factory=list)


class NonEmergencyRoutingRules(BaseModel):
    during_hours: NonEmergencyDuringHours = Field(default_factory=NonEmergencyDuringHours)
    after_hours: NonEmergencyAfterHours = Field(default_factory=NonEmergencyAfterHours)


class CallTransferRules(BaseModel):
    timeout_seconds: int = Field(default=30)
    max_retries: int = Field(default=2)
    failure_message: str = Field(default="")


class AccountMemo(BaseModel):
    account_id: str = Field(default="")
    company_name: str = Field(default="")
    business_hours: BusinessHours = Field(default_factory=BusinessHours)
    office_address: str = Field(default="")
    services_supported: List[str] = Field(default_factory=list)
    emergency_definition: List[str] = Field(default_factory=list)
    emergency_routing_rules: EmergencyRoutingRules = Field(default_factory=EmergencyRoutingRules)
    non_emergency_routing_rules: NonEmergencyRoutingRules = Field(default_factory=NonEmergencyRoutingRules)
    call_transfer_rules: CallTransferRules = Field(default_factory=CallTransferRules)
    integration_constraints: List[str] = Field(default_factory=list)
    after_hours_flow_summary: str = Field(default="")
    office_hours_flow_summary: str = Field(default="")
    questions_or_unknowns: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class KeyVariables(BaseModel):
    timezone: str = Field(default="")
    business_hours: str = Field(default="")
    address: str = Field(default="")
    emergency_routing: Dict[str, Any] = Field(default_factory=dict)


class CallTransferProtocolEntry(BaseModel):
    step: str = Field(default="")
    target: str = Field(default="")
    timeout: str = Field(default="")
    on_failure: str = Field(default="")


class CallTransferProtocol(BaseModel):
    during_hours: List[CallTransferProtocolEntry] = Field(default_factory=list)
    after_hours: List[CallTransferProtocolEntry] = Field(default_factory=list)


class FallbackProtocol(BaseModel):
    all_lines_busy: str = Field(default="")
    technical_failure: str = Field(default="")


class RetellAgentSpec(BaseModel):
    agent_name: str = Field(default="")
    voice_style: str = Field(default="professional, warm, and clear")
    system_prompt: str = Field(default="")
    key_variables: KeyVariables = Field(default_factory=KeyVariables)
    tool_invocation_placeholders: List[str] = Field(default_factory=list)
    call_transfer_protocol: CallTransferProtocol = Field(default_factory=CallTransferProtocol)
    fallback_protocol: FallbackProtocol = Field(default_factory=FallbackProtocol)
    version: str = Field(default="v1")
