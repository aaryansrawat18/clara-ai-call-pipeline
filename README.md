# Clara Answers — AI Call Processing Automation Pipeline

> **Zero-cost automation pipeline** for processing demo & onboarding call transcripts to generate Retell AI Agent configurations and account memos, with a management dashboard.

---

<<<<<<< HEAD

=======
## video Demo:
 https://drive.google.com/drive/folders/1NRh83FRXI4BI9xUa1OU6pSQqF5dvdTEa?usp=sharing
>>>>>>> 6c6e79a78d33f0383c21a22421a4d1cb61431515

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Clara Answers Pipeline                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────────┐   │
│  │Transcripts│───▶│ batch_process│───▶│  TranscriptProcessor │   │
│  │ (10 files)│    │    .py       │    │     (processor.py)   │   │
│  └──────────┘    └──────┬───────┘    └──────────┬───────────┘   │
│                         │                        │               │
│                   ┌─────▼─────┐          ┌──────▼──────┐        │
│                   │  Webhook  │          │  LLM Client │        │
│                   │  (n8n)    │          │ Groq/Ollama │        │
│                   └───────────┘          │ /Rule-based │        │
│                                          └──────┬──────┘        │
│                                                  │               │
│                         ┌────────────────────────▼──────┐       │
│                         │      /outputs/accounts/       │       │
│                         │   /<account_id>/v1/memo.json  │       │
│                         │   /<account_id>/v1/agent_spec │       │
│                         │   /<account_id>/v2/memo.json  │       │
│                         │   /<account_id>/v2/agent_spec │       │
│                         │   /<account_id>/changelog.md  │       │
│                         └──────────────┬────────────────┘       │
│                                        │                         │
│              ┌─────────────────────────▼──────────────┐         │
│              │         Dashboard (FastAPI + React)     │         │
│              │  • Account list with missing-data flags │         │
│              │  • Side-by-side diff viewer (v1 → v2)  │         │
│              │  • Processing metrics                   │         │
│              └────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Demo Call (Pipeline A)**: Transcript → Extract Account Memo → Generate Retell Agent Spec v1 → Save to `/outputs/accounts/<id>/v1/`
2. **Onboarding Call (Pipeline B)**: Transcript → Load v1 → Update Memo → Generate Agent Spec v2 → Generate Changelog → Save to `v2/`
3. **Dashboard**: FastAPI reads outputs → computes diffs with `difflib` → React frontend displays everything

---

## 💰 Zero-Cost Guarantee

| Component | Cost | Details |
|-----------|------|---------|
| **LLM Extraction** | $0 | Groq free-tier (primary) or Ollama local (secondary) or rule-based regex fallback (guaranteed) |
| **n8n** | $0 | Self-hosted, open-source |
| **Ollama** | $0 | Local LLM inference, open-source |
| **FastAPI** | $0 | Open-source Python framework |
| **React/Vite** | $0 | Open-source frontend tooling |
| **Docker** | $0 | Free for personal use |

> **The pipeline runs fully offline** using the rule-based fallback. No API keys required for basic operation.

---

## 📂 Repository Structure

```
clara-answers/
├── transcripts/                    # 10 sample call transcripts
│   ├── demo_call_01_dental.txt
│   ├── demo_call_02_plumbing.txt
│   ├── demo_call_03_legal.txt
│   ├── demo_call_04_veterinary.txt
│   ├── demo_call_05_hvac.txt
│   ├── onboarding_call_01_dental.txt
│   ├── onboarding_call_02_plumbing.txt
│   ├── onboarding_call_03_legal.txt
│   ├── onboarding_call_04_veterinary.txt
│   └── onboarding_call_05_hvac.txt
├── workflows/
│   └── n8n_pipeline_export.json    # Importable n8n workflow
├── outputs/                        # Generated at runtime
│   └── accounts/
│       └── <account_id>/
│           ├── v1/
│           │   ├── memo.json
│           │   └── agent_spec.json
│           ├── v2/
│           │   ├── memo.json
│           │   └── agent_spec.json
│           ├── changelog.md
│           ├── task_demo.json
│           └── task_onboarding.json
├── scripts/
│   ├── batch_process.py            # Batch processor (standalone/webhook)
│   ├── processor.py                # Core extraction & generation engine
│   ├── llm_client.py               # Multi-backend LLM client
│   ├── schemas.py                  # Pydantic data models
│   └── requirements.txt
├── schemas/
│   ├── account_memo_schema.json    # Reference JSON schema
│   └── agent_spec_schema.json
├── dashboard/
│   ├── backend/
│   │   ├── main.py                 # FastAPI server
│   │   ├── diff_engine.py          # Diff computation engine
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   └── frontend/
│       ├── src/
│       │   ├── App.jsx             # React dashboard
│       │   ├── index.css           # Premium dark theme
│       │   └── main.jsx
│       ├── index.html
│       ├── vite.config.js
│       ├── nginx.conf
│       ├── Dockerfile
│       └── package.json
├── docker-compose.yml              # Full stack orchestration
├── requirements.txt                # Root Python dependencies
├── .gitignore
└── README.md                       # This file
```

---

## 🚀 Quick Start

### Option 1: Standalone Mode (Fastest, No Docker Required)

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Run the batch processor (processes all 10 transcripts)
python scripts/batch_process.py --mode=standalone

# 3. Check outputs
ls outputs/accounts/
# → bright_smile_dental/  quickfix_plumbing_co/  hartfield__associates_law_firm/  ...

# 4. Start the dashboard backend
cd dashboard/backend
pip install -r requirements.txt
python -m uvicorn main:app --port 8000

# 5. In another terminal, start the frontend
cd dashboard/frontend
npm install
npm run dev

# 6. Open http://localhost:3000 in your browser
```

### Option 2: Docker Compose (Full Stack)

```bash
# 1. Start everything
docker compose up -d

# 2. Wait for Ollama to pull the model (~2-3 min on first run)
docker logs -f clara-ollama-pull

# 3. Import the n8n workflow
#    Open http://localhost:5678
#    → Import workflow from workflows/n8n_pipeline_export.json

# 4. Run batch processing (from host machine)
pip install -r scripts/requirements.txt
python scripts/batch_process.py --mode=standalone

# 5. Open the dashboard
#    → http://localhost:3000

# 6. To stop everything
docker compose down
```

### Option 3: With Groq Free-Tier API (Better Extraction Quality)

```bash
# 1. Get a free API key from https://console.groq.com
# 2. Set the environment variable
export GROQ_API_KEY=gsk_your_key_here     # Linux/Mac
set GROQ_API_KEY=gsk_your_key_here        # Windows

# 3. Run the batch processor
python scripts/batch_process.py --mode=standalone
# The processor will automatically use Groq for better results
```

---

## 📊 Data Schemas

### Account Memo

| Field | Type | Description |
|-------|------|-------------|
| `account_id` | string | Unique ID derived from company name |
| `company_name` | string | Full business name |
| `business_hours` | object | `{days, start, end, timezone, exceptions}` |
| `office_address` | string | Full address if mentioned |
| `services_supported` | list | All services offered |
| `emergency_definition` | list | What constitutes an emergency |
| `emergency_routing_rules` | object | During-hours and after-hours routing chains |
| `non_emergency_routing_rules` | object | Routine call handling |
| `call_transfer_rules` | object | Timeouts, retries, failure messages |
| `integration_constraints` | list | Software/tools in use |
| `after_hours_flow_summary` | string | Natural language summary |
| `office_hours_flow_summary` | string | Natural language summary |
| `questions_or_unknowns` | list | Missing/unclear information |
| `notes` | list | Greetings, special instructions |

### Retell Agent Draft Spec

| Field | Type | Description |
|-------|------|-------------|
| `agent_name` | string | e.g., "Bright Smile Dental AI Receptionist" |
| `voice_style` | string | e.g., "professional, warm, and clear" |
| `system_prompt` | string | Complete, production-ready AI prompt |
| `key_variables` | object | Timezone, hours, address, routing |
| `tool_invocation_placeholders` | list | e.g., `["transfer_call", "take_message"]` |
| `call_transfer_protocol` | object | During-hours and after-hours step chains |
| `fallback_protocol` | object | All-lines-busy and technical-failure messages |
| `version` | string | `"v1"` or `"v2"` |

---

## 🔧 n8n Workflow

The workflow JSON (`workflows/n8n_pipeline_export.json`) contains two pipelines:

### Pipeline A — Demo Call
`Webhook → Parse Transcript → Extract Memo (Ollama) → Parse Response → Generate Agent Spec → Save v1 Artifacts`

### Pipeline B — Onboarding Call
`Webhook → Parse Transcript → Load v1 Data → Update Memo (Ollama) → Parse Response → Generate Spec v2 → Save v2 + Changelog`

**To import:**
1. Open n8n at `http://localhost:5678`
2. Click `+` → `Import from File`
3. Select `workflows/n8n_pipeline_export.json`
4. Activate the workflow

**Error handling:** Each LLM node has 3 retries with 2-second backoff. The error handler node logs failures and suggests fixes.

---

## 🖥️ Dashboard Features

| Feature | Description |
|---------|-------------|
| **Account List** | Cards for each processed account with version badges |
| **Missing Data Highlights** | ⚠️ badges showing incomplete fields |
| **Diff Viewer** | Side-by-side comparison of v1→v2 changes |
| **Prompt Diff** | Unified diff of the system prompt changes |
| **Metrics Panel** | Success/failure counts, processing times |
| **Detail Panel** | Tabbed view: Overview, Diff, v1 Data, v2 Data |

---

## 🧠 LLM Strategy

The pipeline uses a **three-tier fallback** strategy for zero-cost guarantee:

| Priority | Backend | Requirements | Quality |
|----------|---------|-------------|---------|
| 1️⃣ | **Groq** | Free API key from [console.groq.com](https://console.groq.com) | ⭐⭐⭐⭐⭐ Best |
| 2️⃣ | **Ollama** | Docker or local install, ~2GB RAM | ⭐⭐⭐⭐ Good |
| 3️⃣ | **Rule-based** | Nothing — built-in regex | ⭐⭐⭐ Adequate |

The system auto-detects the best available backend at startup.

---

## ⚠️ Known Limitations

1. **Rule-based extraction** may miss nuanced information from transcripts compared to LLM extraction
2. **n8n webhook mode** requires n8n to be running (standalone mode works without it)
3. **Ollama** requires significant RAM (~4GB for llama3.2:3b) — use Groq or rule-based fallback on low-memory machines
4. **Transcript format** must follow the timestamped format `[MM:SS] Speaker: Text` for best results
5. **No real call integration** — this is a demo/prototype using sample transcripts
6. **Frontend** proxies API via Vite in dev mode; in production Docker uses nginx proxy

---

## 📋 Plugging in Your Own Transcripts

1. Add your transcript files to the `/transcripts/` directory
2. Follow the naming convention: `demo_call_XX_<type>.txt` and `onboarding_call_XX_<type>.txt`
3. Update the `TRANSCRIPT_PAIRS` mapping in `scripts/processor.py` to include your new files
4. Run: `python scripts/batch_process.py --mode=standalone`

---

## 🧪 Testing

```bash
# Run batch processor and verify outputs
python scripts/batch_process.py --mode=standalone

# Check that all 5 accounts have v1 and v2 data
python -c "
import os
accounts = os.listdir('outputs/accounts')
for a in accounts:
    v1 = os.path.exists(f'outputs/accounts/{a}/v1/memo.json')
    v2 = os.path.exists(f'outputs/accounts/{a}/v2/memo.json')
    cl = os.path.exists(f'outputs/accounts/{a}/changelog.md')
    print(f'{a}: v1={v1} v2={v2} changelog={cl}')
"

# Test the API
curl http://localhost:8000/api/accounts
curl http://localhost:8000/api/metrics
```

---

## 📄 License

MIT — Free for any use.
