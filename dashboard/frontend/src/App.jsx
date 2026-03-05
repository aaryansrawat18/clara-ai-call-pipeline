import React, { useState, useEffect } from 'react'

const API_BASE = '/api'

// ─── API Helper ────────────────────────────────────────────────────
async function fetchJSON(url) {
    const res = await fetch(`${API_BASE}${url}`)
    if (!res.ok) throw new Error(`API Error: ${res.status} ${res.statusText}`)
    return res.json()
}

// ─── Metrics Bar ───────────────────────────────────────────────────
function MetricsBar({ metrics }) {
    if (!metrics) return null
    return (
        <div className="metrics-bar">
            <div className="metric-card">
                <div className="label">Total Accounts</div>
                <div className="value accent">{(metrics.demo_calls?.success || 0)}</div>
            </div>
            <div className="metric-card">
                <div className="label">Demo Calls</div>
                <div className="value success">{metrics.demo_calls?.success || 0}/{metrics.demo_calls?.total || 0}</div>
            </div>
            <div className="metric-card">
                <div className="label">Onboarding Calls</div>
                <div className="value success">{metrics.onboarding_calls?.success || 0}/{metrics.onboarding_calls?.total || 0}</div>
            </div>
            <div className="metric-card">
                <div className="label">Failed</div>
                <div className="value warning">{metrics.total_failed || 0}</div>
            </div>
        </div>
    )
}

// ─── Account Card ──────────────────────────────────────────────────
function AccountCard({ account, onClick }) {
    const hasMissing = account.missing_fields_v1?.length > 0 || account.missing_fields_v2?.length > 0
    const latestMissing = account.has_v2 ? account.missing_fields_v2 : account.missing_fields_v1

    return (
        <div className="account-card" onClick={() => onClick(account.account_id)}>
            <div className="company-name">{account.company_name}</div>
            <div className="account-id">{account.account_id}</div>
            <div className="badges">
                {account.has_v1 && <span className="badge v1">v1 Demo</span>}
                {account.has_v2 && <span className="badge v2">v2 Onboarding</span>}
                {account.has_changelog && <span className="badge changelog">Changelog</span>}
                {hasMissing && <span className="badge missing">{latestMissing.length} Missing</span>}
            </div>
            <div className="stats-row">
                <span>📋 {account.services_count} services</span>
                <span>🚨 {account.emergency_count} emergencies</span>
                {account.unknowns_count > 0 && <span>❓ {account.unknowns_count} unknowns</span>}
            </div>
            {latestMissing?.length > 0 && (
                <div className="missing-fields">
                    ⚠ Missing: {latestMissing.slice(0, 3).join(', ')}
                    {latestMissing.length > 3 && ` +${latestMissing.length - 3} more`}
                </div>
            )}
        </div>
    )
}

// ─── Diff Viewer ───────────────────────────────────────────────────
function DiffViewer({ diff }) {
    if (!diff) return <div className="loading"><div className="spinner" /><span>Loading diff...</span></div>

    const { memo_diff, spec_diff, summary } = diff

    return (
        <div>
            <div className="diff-summary">
                <div className="diff-stat">
                    <div className="number changes">{summary.total_changes}</div>
                    <div className="label">Total Changes</div>
                </div>
                <div className="diff-stat">
                    <div className="number additions">+{summary.prompt_additions}</div>
                    <div className="label">Prompt Additions</div>
                </div>
                <div className="diff-stat">
                    <div className="number deletions">-{summary.prompt_deletions}</div>
                    <div className="label">Prompt Deletions</div>
                </div>
            </div>

            {memo_diff.changes.length > 0 && (
                <div className="diff-section">
                    <h3>📝 Account Memo Changes ({memo_diff.total_changes})</h3>
                    {memo_diff.changes.map((change, i) => (
                        <DiffItem key={i} change={change} />
                    ))}
                </div>
            )}

            {spec_diff.prompt_changed && (
                <div className="diff-section">
                    <h3>🤖 System Prompt Changes</h3>
                    <div className="prompt-diff">
                        {spec_diff.prompt_diff.unified_diff.map((line, i) => {
                            let className = ''
                            if (line.startsWith('+')) className = 'line-add'
                            else if (line.startsWith('-')) className = 'line-remove'
                            else if (line.startsWith('@@')) className = 'line-header'
                            return <div key={i} className={className}>{line}</div>
                        })}
                    </div>
                </div>
            )}

            {spec_diff.changes.length > 0 && (
                <div className="diff-section">
                    <h3>⚙️ Spec Field Changes ({spec_diff.total_changes})</h3>
                    {spec_diff.changes.map((change, i) => (
                        <DiffItem key={i} change={change} />
                    ))}
                </div>
            )}
        </div>
    )
}

function DiffItem({ change }) {
    if (change.type === 'modified_list') {
        return (
            <div className="diff-item modified">
                <div className="path">{change.path}</div>
                <div className="list-changes">
                    {change.added?.map((item, i) => (
                        <span key={`a-${i}`} className="added-item">+ {item}</span>
                    ))}
                    {change.removed?.map((item, i) => (
                        <span key={`r-${i}`} className="removed-item">- {item}</span>
                    ))}
                </div>
            </div>
        )
    }

    return (
        <div className={`diff-item ${change.type}`}>
            <div className="path">{change.path}</div>
            {change.type === 'modified' && (
                <div className="values">
                    <div className="old-val">{JSON.stringify(change.old_value, null, 2)}</div>
                    <div className="new-val">{JSON.stringify(change.new_value, null, 2)}</div>
                </div>
            )}
            {change.type === 'added' && (
                <div className="new-val" style={{ marginTop: 8 }}>
                    {JSON.stringify(change.new_value, null, 2)}
                </div>
            )}
            {change.type === 'removed' && (
                <div className="old-val" style={{ marginTop: 8 }}>
                    {JSON.stringify(change.old_value, null, 2)}
                </div>
            )}
        </div>
    )
}

// ─── Detail Panel ──────────────────────────────────────────────────
function DetailPanel({ accountId, onClose }) {
    const [data, setData] = useState(null)
    const [diff, setDiff] = useState(null)
    const [tab, setTab] = useState('overview')
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)

    useEffect(() => {
        setLoading(true)
        setError(null)

        Promise.all([
            fetchJSON(`/accounts/${accountId}`),
            fetchJSON(`/accounts/${accountId}/diff`).catch(() => null)
        ])
            .then(([accountData, diffData]) => {
                setData(accountData)
                setDiff(diffData)
                setLoading(false)
            })
            .catch(err => {
                setError(err.message)
                setLoading(false)
            })
    }, [accountId])

    if (loading) return (
        <>
            <div className="overlay" onClick={onClose} />
            <div className="detail-panel">
                <div className="loading"><div className="spinner" /><span>Loading account data...</span></div>
            </div>
        </>
    )

    if (error) return (
        <>
            <div className="overlay" onClick={onClose} />
            <div className="detail-panel">
                <div className="panel-header">
                    <h2>Error</h2>
                    <button className="close-btn" onClick={onClose}>×</button>
                </div>
                <div className="panel-content">
                    <div className="error-msg">{error}</div>
                </div>
            </div>
        </>
    )

    return (
        <>
            <div className="overlay" onClick={onClose} />
            <div className="detail-panel">
                <div className="panel-header">
                    <div>
                        <h2 style={{ fontSize: 20, fontWeight: 700 }}>
                            {data?.v2?.memo?.company_name || data?.v1?.memo?.company_name || accountId}
                        </h2>
                        <span style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'monospace' }}>{accountId}</span>
                    </div>
                    <button className="close-btn" onClick={onClose}>×</button>
                </div>

                <div className="panel-content">
                    <div className="tabs">
                        <button className={`tab ${tab === 'overview' ? 'active' : ''}`} onClick={() => setTab('overview')}>
                            Overview
                        </button>
                        <button className={`tab ${tab === 'diff' ? 'active' : ''}`} onClick={() => setTab('diff')}
                            disabled={!diff}>
                            Diff Viewer
                        </button>
                        <button className={`tab ${tab === 'v1' ? 'active' : ''}`} onClick={() => setTab('v1')}>
                            v1 Data
                        </button>
                        <button className={`tab ${tab === 'v2' ? 'active' : ''}`} onClick={() => setTab('v2')}
                            disabled={!data?.v2?.memo}>
                            v2 Data
                        </button>
                    </div>

                    {tab === 'overview' && data && (
                        <div>
                            <div className="diff-section">
                                <h3>📊 Account Summary</h3>
                                <div className="diff-summary" style={{ gridTemplateColumns: 'repeat(2, 1fr)' }}>
                                    <div className="diff-stat">
                                        <div className="number accent">
                                            {(data.v2?.memo || data.v1?.memo)?.services_supported?.length || 0}
                                        </div>
                                        <div className="label">Services</div>
                                    </div>
                                    <div className="diff-stat">
                                        <div className="number warning">
                                            {(data.v2?.memo || data.v1?.memo)?.emergency_definition?.length || 0}
                                        </div>
                                        <div className="label">Emergency Types</div>
                                    </div>
                                </div>
                            </div>

                            {data.v1?.memo?.questions_or_unknowns?.length > 0 && (
                                <div className="diff-section">
                                    <h3>❓ Open Questions</h3>
                                    {data.v1.memo.questions_or_unknowns.map((q, i) => (
                                        <div key={i} className="diff-item modified">
                                            <div className="path">Question #{i + 1}</div>
                                            <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>{q}</div>
                                        </div>
                                    ))}
                                </div>
                            )}

                            {data.changelog && (
                                <div className="diff-section">
                                    <h3>📋 Changelog</h3>
                                    <div className="json-viewer" style={{ whiteSpace: 'pre-wrap' }}>
                                        {data.changelog}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {tab === 'diff' && <DiffViewer diff={diff} />}

                    {tab === 'v1' && data?.v1 && (
                        <div>
                            <div className="diff-section">
                                <h3>📝 v1 Account Memo</h3>
                                <div className="json-viewer">{JSON.stringify(data.v1.memo, null, 2)}</div>
                            </div>
                            <div className="diff-section">
                                <h3>🤖 v1 Agent Spec</h3>
                                <div className="json-viewer">{JSON.stringify(data.v1.agent_spec, null, 2)}</div>
                            </div>
                        </div>
                    )}

                    {tab === 'v2' && data?.v2 && (
                        <div>
                            <div className="diff-section">
                                <h3>📝 v2 Account Memo</h3>
                                <div className="json-viewer">{JSON.stringify(data.v2.memo, null, 2)}</div>
                            </div>
                            <div className="diff-section">
                                <h3>🤖 v2 Agent Spec</h3>
                                <div className="json-viewer">{JSON.stringify(data.v2.agent_spec, null, 2)}</div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </>
    )
}

// ─── Upload Modal ──────────────────────────────────────────────────
function UploadModal({ accounts, onClose, onSuccess }) {
    const [transcript, setTranscript] = useState('')
    const [callType, setCallType] = useState('demo')
    const [accountId, setAccountId] = useState('')
    const [submitting, setSubmitting] = useState(false)
    const [result, setResult] = useState(null)
    const [error, setError] = useState(null)

    const handleSubmit = async () => {
        if (!transcript.trim()) { setError('Please paste a transcript.'); return }
        if (callType === 'onboarding' && !accountId) { setError('Select an account for onboarding.'); return }

        setSubmitting(true)
        setError(null)
        setResult(null)

        try {
            const res = await fetch(`${API_BASE}/process`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    transcript,
                    call_type: callType,
                    account_id: callType === 'onboarding' ? accountId : undefined
                })
            })
            const data = await res.json()

            if (!res.ok) {
                setError(data.detail || 'Processing failed.')
                setSubmitting(false)
                return
            }

            setResult(data)
            setSubmitting(false)
        } catch (e) {
            setError(e.message)
            setSubmitting(false)
        }
    }

    const handleFileUpload = (e) => {
        const file = e.target.files?.[0]
        if (!file) return
        const reader = new FileReader()
        reader.onload = (ev) => setTranscript(ev.target.result)
        reader.readAsText(file)
    }

    return (
        <>
            <div className="overlay" onClick={onClose} />
            <div className="upload-modal">
                <div className="panel-header">
                    <h2 style={{ fontSize: 20, fontWeight: 700 }}>📤 Process Transcript</h2>
                    <button className="close-btn" onClick={onClose}>×</button>
                </div>

                <div className="panel-content">
                    {result ? (
                        <div className="upload-result">
                            <div className="result-icon">✅</div>
                            <h3>{result.message}</h3>
                            <div className="result-details">
                                <div><strong>Account:</strong> {result.account_id}</div>
                                <div><strong>Version:</strong> {result.version}</div>
                                {result.services_count !== undefined && (
                                    <div><strong>Services extracted:</strong> {result.services_count}</div>
                                )}
                                {result.changelog_lines && (
                                    <div><strong>Changelog lines:</strong> {result.changelog_lines}</div>
                                )}
                            </div>
                            <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
                                <button className="upload-btn" onClick={() => { onSuccess(); onClose() }}>
                                    Done — Refresh Dashboard
                                </button>
                                <button className="upload-btn secondary" onClick={() => { setResult(null); setTranscript('') }}>
                                    Process Another
                                </button>
                            </div>
                        </div>
                    ) : (
                        <>
                            {/* Call Type Selector */}
                            <div className="form-group">
                                <label>Call Type</label>
                                <div className="tabs" style={{ marginBottom: 0 }}>
                                    <button
                                        className={`tab ${callType === 'demo' ? 'active' : ''}`}
                                        onClick={() => setCallType('demo')}
                                    >
                                        🎯 Demo Call (v1)
                                    </button>
                                    <button
                                        className={`tab ${callType === 'onboarding' ? 'active' : ''}`}
                                        onClick={() => setCallType('onboarding')}
                                    >
                                        📋 Onboarding Call (v2)
                                    </button>
                                </div>
                            </div>

                            {/* Account selector for onboarding */}
                            {callType === 'onboarding' && (
                                <div className="form-group">
                                    <label>Select Account to Update</label>
                                    <select
                                        className="form-select"
                                        value={accountId}
                                        onChange={(e) => setAccountId(e.target.value)}
                                    >
                                        <option value="">— Select an account —</option>
                                        {accounts.filter(a => a.has_v1).map(a => (
                                            <option key={a.account_id} value={a.account_id}>
                                                {a.company_name} ({a.account_id})
                                            </option>
                                        ))}
                                    </select>
                                </div>
                            )}

                            {/* Transcript Input */}
                            <div className="form-group">
                                <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    Transcript
                                    <label className="file-upload-label">
                                        📁 Upload .txt
                                        <input type="file" accept=".txt" onChange={handleFileUpload} hidden />
                                    </label>
                                </label>
                                <textarea
                                    className="form-textarea"
                                    placeholder={`Paste your ${callType} call transcript here...\n\nExample format:\nDEMO CALL TRANSCRIPT — Company Name\n[00:00] Speaker: Text...`}
                                    value={transcript}
                                    onChange={(e) => setTranscript(e.target.value)}
                                    rows={14}
                                />
                                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                                    {transcript ? `${transcript.length.toLocaleString()} characters` : 'No transcript loaded'}
                                </div>
                            </div>

                            {error && <div className="error-msg" style={{ marginBottom: 16 }}>{error}</div>}

                            <button
                                className="upload-btn"
                                onClick={handleSubmit}
                                disabled={submitting || !transcript.trim()}
                            >
                                {submitting ? (
                                    <><div className="spinner" style={{ width: 16, height: 16, borderWidth: 2, marginRight: 8, display: 'inline-block' }} /> Processing...</>
                                ) : (
                                    `🚀 Process ${callType === 'demo' ? 'Demo' : 'Onboarding'} Call`
                                )}
                            </button>
                        </>
                    )}
                </div>
            </div>
        </>
    )
}

// ─── App ───────────────────────────────────────────────────────────
export default function App() {
    const [accounts, setAccounts] = useState([])
    const [metrics, setMetrics] = useState(null)
    const [selectedAccount, setSelectedAccount] = useState(null)
    const [showUpload, setShowUpload] = useState(false)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)

    const loadData = () => {
        setLoading(true)
        setError(null)

        Promise.all([
            fetchJSON('/accounts'),
            fetchJSON('/metrics').catch(() => null)
        ])
            .then(([accountsData, metricsData]) => {
                setAccounts(accountsData)
                setMetrics(metricsData)
                setLoading(false)
            })
            .catch(err => {
                setError(err.message)
                setLoading(false)
            })
    }

    useEffect(() => { loadData() }, [])

    return (
        <div className="app">
            <header>
                <div>
                    <h1>Clara Answers</h1>
                    <div className="subtitle">AI Call Processing Dashboard</div>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                    <button className="upload-btn" onClick={() => setShowUpload(true)}>
                        📤 Add Transcript
                    </button>
                    <button className="refresh-btn" onClick={loadData}>
                        🔄 Refresh
                    </button>
                </div>
            </header>

            {error && <div className="error-msg">{error}</div>}

            <MetricsBar metrics={metrics} />

            {loading ? (
                <div className="loading">
                    <div className="spinner" />
                    <span>Loading accounts...</span>
                </div>
            ) : accounts.length === 0 ? (
                <div className="empty-state">
                    <div className="icon">📭</div>
                    <h2>No Accounts Processed</h2>
                    <p>Run the batch processor to generate account data:
                        <code style={{ display: 'block', marginTop: 8, padding: 8, background: 'var(--bg-glass)', borderRadius: 6, fontSize: 13 }}>
                            python scripts/batch_process.py --mode=standalone
                        </code>
                    </p>
                </div>
            ) : (
                <>
                    <h2 className="section-title">📁 Processed Accounts ({accounts.length})</h2>
                    <div className="accounts-grid">
                        {accounts.map(account => (
                            <AccountCard
                                key={account.account_id}
                                account={account}
                                onClick={setSelectedAccount}
                            />
                        ))}
                    </div>
                </>
            )}

            {selectedAccount && (
                <DetailPanel
                    accountId={selectedAccount}
                    onClose={() => setSelectedAccount(null)}
                />
            )}

            {showUpload && (
                <UploadModal
                    accounts={accounts}
                    onClose={() => setShowUpload(false)}
                    onSuccess={loadData}
                />
            )}
        </div>
    )
}
