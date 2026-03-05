"""
FastAPI backend for Clara Answers Dashboard.
Serves account data, diffs, and batch metrics.
Supports transcript upload and processing.
"""

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from diff_engine import compute_full_diff, find_missing_fields

# Add scripts directory to path so we can import the processor
SCRIPTS_DIR = str(Path(__file__).parent.parent.parent / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

# ─── CONFIG ──────────────────────────────────────────────────────────

OUTPUTS_DIR = Path(os.environ.get(
    "OUTPUTS_DIR",
    str(Path(__file__).parent.parent.parent / "outputs" / "accounts")
))

app = FastAPI(
    title="Clara Answers Dashboard API",
    description="Backend API for the Clara Answers management dashboard",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── MODELS ──────────────────────────────────────────────────────────

class AccountSummary(BaseModel):
    account_id: str
    company_name: str
    has_v1: bool
    has_v2: bool
    has_changelog: bool
    missing_fields_v1: List[str]
    missing_fields_v2: List[str]
    services_count: int
    emergency_count: int
    unknowns_count: int


class BatchMetricsResponse(BaseModel):
    demo_calls: Dict[str, int]
    onboarding_calls: Dict[str, int]
    total_processed: int
    total_failed: int
    total_elapsed_seconds: float
    errors: List[Dict]


class ProcessRequest(BaseModel):
    transcript: str
    call_type: str  # "demo" or "onboarding"
    account_id: Optional[str] = None  # Required for onboarding calls


# ─── HELPERS ─────────────────────────────────────────────────────────

def _load_json(path: Path) -> Optional[Dict]:
    """Safely load a JSON file."""
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _get_account_ids() -> List[str]:
    """Get all account IDs from the outputs directory."""
    if not OUTPUTS_DIR.exists():
        return []
    return sorted([
        d.name for d in OUTPUTS_DIR.iterdir()
        if d.is_dir() and (d / "v1").exists()
    ])


# ─── ENDPOINTS ───────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"service": "Clara Answers Dashboard API", "version": "1.0.0"}


@app.get("/api/accounts", response_model=List[AccountSummary])
async def list_accounts():
    """List all processed accounts with summary information."""
    accounts = []
    for account_id in _get_account_ids():
        account_dir = OUTPUTS_DIR / account_id

        v1_memo = _load_json(account_dir / "v1" / "memo.json")
        v2_memo = _load_json(account_dir / "v2" / "memo.json")
        has_changelog = (account_dir / "changelog.md").exists()

        # Use latest memo for stats
        latest_memo = v2_memo or v1_memo or {}

        accounts.append(AccountSummary(
            account_id=account_id,
            company_name=latest_memo.get("company_name", account_id),
            has_v1=v1_memo is not None,
            has_v2=v2_memo is not None,
            has_changelog=has_changelog,
            missing_fields_v1=find_missing_fields(v1_memo) if v1_memo else ["All fields missing"],
            missing_fields_v2=find_missing_fields(v2_memo) if v2_memo else [],
            services_count=len(latest_memo.get("services_supported", [])),
            emergency_count=len(latest_memo.get("emergency_definition", [])),
            unknowns_count=len(latest_memo.get("questions_or_unknowns", []))
        ))

    return accounts


@app.get("/api/accounts/{account_id}")
async def get_account(account_id: str):
    """Get full v1 and v2 data for an account."""
    account_dir = OUTPUTS_DIR / account_id

    if not account_dir.exists():
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

    v1_memo = _load_json(account_dir / "v1" / "memo.json")
    v1_spec = _load_json(account_dir / "v1" / "agent_spec.json")
    v2_memo = _load_json(account_dir / "v2" / "memo.json")
    v2_spec = _load_json(account_dir / "v2" / "agent_spec.json")

    # Load changelog
    changelog = ""
    changelog_path = account_dir / "changelog.md"
    if changelog_path.exists():
        with open(changelog_path, "r", encoding="utf-8") as f:
            changelog = f.read()

    # Load task trackers
    demo_task = _load_json(account_dir / "task_demo.json")
    onboarding_task = _load_json(account_dir / "task_onboarding.json")

    return {
        "account_id": account_id,
        "v1": {
            "memo": v1_memo,
            "agent_spec": v1_spec
        },
        "v2": {
            "memo": v2_memo,
            "agent_spec": v2_spec
        },
        "changelog": changelog,
        "tasks": {
            "demo": demo_task,
            "onboarding": onboarding_task
        }
    }


@app.get("/api/accounts/{account_id}/diff")
async def get_account_diff(account_id: str):
    """Get computed diff between v1 and v2 for an account."""
    account_dir = OUTPUTS_DIR / account_id

    if not account_dir.exists():
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

    v1_memo = _load_json(account_dir / "v1" / "memo.json")
    v1_spec = _load_json(account_dir / "v1" / "agent_spec.json")
    v2_memo = _load_json(account_dir / "v2" / "memo.json")
    v2_spec = _load_json(account_dir / "v2" / "agent_spec.json")

    if not v1_memo or not v1_spec:
        raise HTTPException(status_code=404, detail="v1 data not found")

    if not v2_memo or not v2_spec:
        raise HTTPException(status_code=404, detail="v2 data not found. Run onboarding pipeline first.")

    diff = compute_full_diff(v1_memo, v2_memo, v1_spec, v2_spec)
    diff["account_id"] = account_id
    diff["company_name"] = v2_memo.get("company_name", account_id)

    return diff


@app.get("/api/accounts/{account_id}/changelog")
async def get_changelog(account_id: str):
    """Get the markdown changelog for an account."""
    changelog_path = OUTPUTS_DIR / account_id / "changelog.md"
    if not changelog_path.exists():
        raise HTTPException(status_code=404, detail="Changelog not found")

    with open(changelog_path, "r", encoding="utf-8") as f:
        return {"account_id": account_id, "changelog": f.read()}


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str):
    """Delete an entire account. This undoes a demo call."""
    import shutil
    account_dir = OUTPUTS_DIR / account_id
    if not account_dir.exists():
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

    try:
        shutil.rmtree(account_dir)
        return {"success": True, "message": f"Account '{account_id}' deleted completely."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete account: {str(e)}")


@app.delete("/api/accounts/{account_id}/v2")
async def revert_onboarding(account_id: str):
    """Delete v2 data and changelog to revert back to demo state."""
    import shutil
    account_dir = OUTPUTS_DIR / account_id
    if not account_dir.exists():
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

    if not (account_dir / "v2").exists():
        raise HTTPException(status_code=404, detail=f"No v2 onboarding data found for {account_id}")

    try:
        # Delete v2 directory
        shutil.rmtree(account_dir / "v2")
        
        # Delete changelog
        if (account_dir / "changelog.md").exists():
            os.remove(account_dir / "changelog.md")
            
        # Delete task tracker
        if (account_dir / "task_onboarding.json").exists():
            os.remove(account_dir / "task_onboarding.json")
            
        return {"success": True, "message": f"Account '{account_id}' reverted to v1 initial state."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to revert onboarding: {str(e)}")


@app.get("/api/metrics")
async def get_metrics():
    """Get batch processing metrics."""
    metrics_path = OUTPUTS_DIR.parent / "batch_metrics.json"

    if metrics_path.exists():
        with open(metrics_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # Generate live metrics from file system
    account_ids = _get_account_ids()
    v2_count = sum(1 for aid in account_ids if (OUTPUTS_DIR / aid / "v2").exists())

    return {
        "demo_calls": {"success": len(account_ids), "failed": 0, "total": len(account_ids)},
        "onboarding_calls": {"success": v2_count, "failed": 0, "total": v2_count},
        "total_processed": len(account_ids) + v2_count,
        "total_failed": 0,
        "total_elapsed_seconds": 0,
        "errors": [],
        "note": "Live metrics from filesystem. Run batch_process.py for detailed metrics."
    }


@app.get("/api/health")
async def health():
    return {"status": "healthy", "outputs_dir": str(OUTPUTS_DIR), "accounts_found": len(_get_account_ids())}


@app.post("/api/process")
async def process_transcript(req: ProcessRequest):
    """Process a transcript (demo or onboarding) and store results."""
    from processor import TranscriptProcessor

    if not req.transcript or not req.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript text is required.")

    if req.call_type not in ("demo", "onboarding"):
        raise HTTPException(status_code=400, detail="call_type must be 'demo' or 'onboarding'.")

    try:
        processor = TranscriptProcessor()

        if req.call_type == "demo":
            memo, spec = processor.process_demo_call(req.transcript, "upload")
            return {
                "success": True,
                "call_type": "demo",
                "account_id": memo.get("account_id", ""),
                "company_name": memo.get("company_name", ""),
                "version": "v1",
                "services_count": len(memo.get("services_supported", [])),
                "emergency_count": len(memo.get("emergency_definition", [])),
                "unknowns_count": len(memo.get("questions_or_unknowns", [])),
                "message": f"Demo call processed. Account '{memo.get('company_name')}' created with v1 data."
            }
        else:
            # Onboarding call — need account_id
            account_id = req.account_id
            if not account_id:
                raise HTTPException(
                    status_code=400,
                    detail="account_id is required for onboarding calls. Select an existing account."
                )

            account_dir = OUTPUTS_DIR / account_id
            if not (account_dir / "v1" / "memo.json").exists():
                raise HTTPException(
                    status_code=404,
                    detail=f"Account '{account_id}' not found or has no v1 data. Process a demo call first."
                )

            updated_memo, updated_spec, changelog = processor.process_onboarding_call(
                req.transcript, account_id, "upload"
            )
            return {
                "success": True,
                "call_type": "onboarding",
                "account_id": account_id,
                "company_name": updated_memo.get("company_name", ""),
                "version": "v2",
                "changelog_lines": len(changelog.splitlines()),
                "message": f"Onboarding call processed. Account '{updated_memo.get('company_name')}' updated to v2."
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@app.post("/api/transcribe")
async def transcribe_audio_file(file: UploadFile = File(...)):
    """Transcribe an uploaded audio file using Whisper."""
    from llm_client import LLMClient
    
    try:
        audio_content = await file.read()
        if not audio_content:
            raise HTTPException(status_code=400, detail="Empty audio file")
            
        client = LLMClient()
        if not client.groq_api_key:
            raise HTTPException(
                status_code=500, 
                detail="Groq API key required for audio transcription. Please set GROQ_API_KEY environment variable."
            )
            
        transcript = client.transcribe_audio(audio_content, file.filename)
        return {"success": True, "text": transcript}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
