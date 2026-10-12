import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { api, ApiError, type ImportPreview } from "../api";

export default function ImportPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function wrap(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return onUnauthorized();
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  function upload(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    wrap(async () => setPreview(await api<ImportPreview>("/api/admin/imports", { method: "POST", form })));
  }

  const commit = () => wrap(async () => {
    await api(`/api/admin/imports/${preview!.id}/commit`, { method: "POST" });
    navigate("/admin");
  });
  const discard = () => wrap(async () => {
    await api(`/api/admin/imports/${preview!.id}`, { method: "DELETE" });
    setPreview(null);
  });

  const s = preview?.summary;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Import orders</h1>
      <form onSubmit={upload} className="space-y-3 rounded-xl bg-white p-4 ring-1 ring-slate-200">
        <p className="text-sm text-slate-600">
          Upload an Excel workbook (.xlsx, up to 2 MB and 1,000 orders) with the columns <b>Name</b>, <b>Product</b>,{" "}
          <b>Contact</b> and <b>Location</b> (a Google Maps link). <b>Delivery Instructions</b> is optional.
          Nothing is saved until you confirm the preview.
        </p>
        <input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          aria-label="Excel file" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="block w-full text-sm file:mr-3 file:min-h-11 file:rounded-md file:border-0 file:bg-slate-800 file:px-4 file:font-semibold file:text-white" />
        <button disabled={!file || busy} className="min-h-11 rounded-md bg-brand-600 px-4 font-semibold text-white disabled:opacity-60">
          {busy && !preview ? "Checking…" : "Upload and preview"}
        </button>
      </form>

      {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}

      {preview && s && (
        <section className="space-y-3" aria-label="Import preview" data-testid="preview">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[["Orders", s.total_rows], ["Rows with errors", s.rows_with_errors], ["Rows with warnings", s.rows_with_warnings], ["Need a pin", s.needs_pin]]
              .map(([label, n]) => (
                <div key={label} className="rounded-lg bg-white p-3 ring-1 ring-slate-200">
                  <p className="text-xs text-slate-500">{label}</p><p className="text-2xl font-semibold">{n}</p>
                </div>
              ))}
          </div>
          {s.file_errors.map((m) => <p key={m} role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{m}</p>)}
          {s.file_warnings.map((m) => <p key={m} className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-950">{m}</p>)}
          {Object.keys(s.mapping).length > 0 && (
            <p className="text-sm text-slate-600">Columns: {Object.entries(s.mapping).map(([from, to]) => from === to ? to : `${from} → ${to}`).join(" · ")}</p>
          )}
          <ul className="space-y-2">
            {preview.rows.filter((r) => r.issues.length > 0).map((r) => (
              <li key={r.row} className="rounded-lg bg-white p-3 text-sm ring-1 ring-slate-200" data-testid="preview-issue">
                <p className="font-semibold">Row {r.row}{r.values.name ? ` · ${r.values.name}` : ""}</p>
                <ul className="mt-1 space-y-1">
                  {r.issues.map((i, k) => (
                    <li key={k} className={i.severity === "error" ? "text-red-800" : "text-amber-900"}>
                      {i.severity === "error" ? "Error" : "Warning"}: {i.message}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
          {preview.rows.length > 0 && preview.rows.every((r) => r.issues.length === 0) && (
            <p className="text-sm text-emerald-800">All rows are valid.</p>
          )}
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={commit} disabled={!s.can_commit || busy}
              className="min-h-11 rounded-md bg-brand-600 px-4 font-semibold text-white disabled:opacity-50">
              Save {s.total_rows} orders
            </button>
            <button type="button" onClick={discard} disabled={busy} className="min-h-11 rounded-md px-4 font-medium ring-1 ring-slate-300">Discard</button>
          </div>
          {!s.can_commit && <p className="text-sm text-slate-600">Fix the errors in the spreadsheet and upload it again. Warnings do not block saving.</p>}
        </section>
      )}
    </div>
  );
}
