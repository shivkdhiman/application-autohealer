const { useState, useEffect, useMemo } = React;

const MAX_NOTES_LENGTH = 2000;

function useRecords() {
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/records");
      if (!res.ok) throw new Error("Failed to load records.");
      const data = await res.json();
      setRecords(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  return { records, loading, error, refresh, setRecords };
}

function RecordForm({ onCreated }) {
  const [form, setForm] = useState({ name: "", dob: "", jobTitle: "", notes: "" });
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const update = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  const validate = () => {
    if (!form.name.trim()) return "Name is required.";
    if (!form.dob.trim()) return "Date of birth is required.";
    if (!form.jobTitle.trim()) return "Job title is required.";
    if (form.notes.length > MAX_NOTES_LENGTH) return `Notes must be ${MAX_NOTES_LENGTH} characters or fewer.`;
    return "";
  };

  const submit = async (e) => {
    e.preventDefault();
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const res = await fetch("/api/records", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to save record.");
      setForm({ name: "", dob: "", jobTitle: "", notes: "" });
      onCreated(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="card form" onSubmit={submit}>
      <h2>New Record</h2>
      {error && <div className="alert">{error}</div>}

      <label>
        Name <span className="required">*</span>
        <input type="text" value={form.name} onChange={update("name")} placeholder="Jane Doe" />
      </label>

      <label>
        Date of Birth <span className="required">*</span>
        <input type="date" value={form.dob} onChange={update("dob")} />
      </label>

      <label>
        Job Title <span className="required">*</span>
        <input type="text" value={form.jobTitle} onChange={update("jobTitle")} placeholder="Software Engineer" />
      </label>

      <label>
        Notes
        <textarea
          rows="4"
          value={form.notes}
          onChange={update("notes")}
          maxLength={MAX_NOTES_LENGTH}
          placeholder="Optional notes..."
        />
        <span className={"char-count" + (form.notes.length >= MAX_NOTES_LENGTH ? " limit" : "")}>
          {form.notes.length} / {MAX_NOTES_LENGTH}
        </span>
      </label>

      <button type="submit" disabled={submitting}>
        {submitting ? "Saving..." : "Save Record"}
      </button>
    </form>
  );
}

function Dashboard({ records, loading, error, refresh, onDeleted }) {
  const [query, setQuery] = useState("");
  const [deletingId, setDeletingId] = useState(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return records;
    return records.filter((r) =>
      [r.name, r.jobTitle, r.notes].filter(Boolean).some((field) => field.toLowerCase().includes(q))
    );
  }, [records, query]);

  const remove = async (id) => {
    if (!window.confirm("Delete this record?")) return;
    setDeletingId(id);
    try {
      const res = await fetch(`/api/records/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete record.");
      onDeleted(id);
    } catch (e) {
      window.alert(e.message);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="card">
      <div className="dashboard-header">
        <h2>Records ({filtered.length})</h2>
        <div className="dashboard-actions">
          <input
            type="text"
            className="search-input"
            placeholder="Search name, job title, notes..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="button" onClick={refresh} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {error && <div className="alert">{error}</div>}

      <div className="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Date of Birth</th>
              <th>Job Title</th>
              <th>Notes</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan="6" className="empty-state">
                  {loading ? "Loading..." : "No records found."}
                </td>
              </tr>
            )}
            {filtered.map((r) => (
              <tr key={r.id}>
                <td>{r.name}</td>
                <td>{r.dob}</td>
                <td>{r.jobTitle}</td>
                <td className="notes-cell" title={r.notes}>{r.notes}</td>
                <td>{new Date(r.createdAt).toLocaleString()}</td>
                <td>
                  <button
                    type="button"
                    className="danger"
                    onClick={() => remove(r.id)}
                    disabled={deletingId === r.id}
                  >
                    {deletingId === r.id ? "Deleting..." : "Delete"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RagMemory() {
  const [cases, setCases] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState(null);

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/rag");
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to load RAG data.");
      setCases(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e.message);
      setCases([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="card">
      <div className="dashboard-header">
        <h2>RAG Memory ({cases.length})</h2>
        <div className="dashboard-actions">
          <button type="button" onClick={refresh} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {error && (
        <div className="alert">
          {error} (Reachable only when running inside the cluster, alongside the autopilot-repairer service.)
        </div>
      )}

      <div className="rag-list">
        {!error && cases.length === 0 && (
          <p className="empty-state">{loading ? "Loading..." : "No repair cases recorded yet."}</p>
        )}
        {cases.map((c, i) => (
          <div className="rag-item" key={i}>
            <div className="rag-item-header" onClick={() => setExpandedId(expandedId === i ? null : i)}>
              <span className="rag-deployment">{c.deployment || "unknown"}</span>
              <span className="rag-action">{c.action}</span>
              <span className="rag-reason">{c.failure_reason}</span>
            </div>
            {expandedId === i && (
              <div className="rag-item-body">
                <p><strong>Pod:</strong> {c.pod_name}</p>
                <p><strong>Outcome:</strong> {c.outcome}</p>
                <pre className="rag-content">{c.content}</pre>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function App() {
  const [tab, setTab] = useState("form");
  const { records, loading, error, refresh, setRecords } = useRecords();

  const handleCreated = (record) => {
    setRecords((prev) => [...prev, record]);
    setTab("dashboard");
  };

  const handleDeleted = (id) => {
    setRecords((prev) => prev.filter((r) => r.id !== id));
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>Records Admin</h1>
        <nav className="tabs">
          <button className={tab === "form" ? "tab active" : "tab"} onClick={() => setTab("form")}>
            New Record
          </button>
          <button className={tab === "dashboard" ? "tab active" : "tab"} onClick={() => setTab("dashboard")}>
            Admin Dashboard
          </button>
          <button className={tab === "rag" ? "tab active" : "tab"} onClick={() => setTab("rag")}>
            RAG Memory
          </button>
        </nav>
      </header>

      <main className="app-main">
        {tab === "form" && <RecordForm onCreated={handleCreated} />}
        {tab === "dashboard" && (
          <Dashboard records={records} loading={loading} error={error} refresh={refresh} onDeleted={handleDeleted} />
        )}
        {tab === "rag" && <RagMemory />}
      </main>
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
