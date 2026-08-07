"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  generateContent,
  getHealth,
  ingestDocument,
  listDocuments,
  recordDecision,
  type AdoptionStage,
  type Channel,
  type ClaimOut,
  type ComplianceFlag,
  type DecisionOut,
  type DocumentOut,
  type GenerateResponse,
  type HealthResponse,
  type IngestResponse,
  type SourceType,
} from "@/lib/api";

const SEVERITY_STYLE: Record<
  string,
  { bar: string; label: string; text: string }
> = {
  blocker: { bar: "bg-[#B3261E]", label: "text-[#B3261E]", text: "Blocker" },
  warning: { bar: "bg-[#8A5A00]", label: "text-[#8A5A00]", text: "Warning" },
  info: { bar: "bg-[#5B6675]", label: "text-[#5B6675]", text: "Note" },
};

const ADOPTION_STAGES: AdoptionStage[] = [
  "unaware",
  "aware",
  "evaluating",
  "occasional_prescriber",
  "advocate",
];

const CHANNELS: Channel[] = ["email", "detail_aid", "follow_up"];
const SOURCE_TYPES: SourceType[] = ["label", "publication", "internal"];

const MONO = { fontFamily: "var(--font-mono)" };
const SERIF = { fontFamily: "var(--font-serif)" };

const INPUT_CLASS =
  "w-full border border-[#D9DEE6] px-2 py-1.5 text-[14px] outline-none focus:border-[#16202E]";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span
        className="mb-1 block text-[11px] uppercase tracking-wider text-[#5B6675]"
        style={MONO}
      >
        {label}
      </span>
      {children}
    </label>
  );
}

function SourceBadge({ type }: { type: SourceType }) {
  const isLabel = type === "label";
  return (
    <span
      className={`px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${
        isLabel
          ? "bg-[#16202E] text-white"
          : "border border-[#D9DEE6] text-[#5B6675]"
      }`}
      style={MONO}
    >
      {type}
    </span>
  );
}

function AnnotatedBody({ body, claims }: { body: string; claims: ClaimOut[] }) {
  const byId = new Map(claims.map((c) => [c.id, c]));
  const parts = body.split(/([[(][a-z0-9-]+-\d{3}[\])])/gi);

  return (
    <p className="whitespace-pre-wrap text-[17px] leading-[1.75]">
      {parts.map((part, i) => {
        const match = part.match(/^[[(]([a-z0-9-]+-\d{3})[\])]$/i);
        const claim = match ? byId.get(match[1]) : undefined;
        if (!claim) return <span key={i}>{part}</span>;
        return (
          <span
            key={i}
            title={`${claim.section} — ${claim.text}`}
            className="mx-0.5 cursor-help rounded-sm border border-[#D9DEE6] bg-white px-1 py-0.5 align-middle text-[11px] text-[#5B6675]"
            style={MONO}
          >
            {claim.id}
          </span>
        );
      })}
    </p>
  );
}

function FlagCard({ flag }: { flag: ComplianceFlag }) {
  const style = SEVERITY_STYLE[flag.severity] ?? SEVERITY_STYLE.info;
  return (
    <div className="relative border border-[#D9DEE6] bg-white px-4 py-3">
      <span className={`absolute left-0 top-0 h-full w-1 ${style.bar}`} />
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <span
          className={`text-[11px] uppercase tracking-wider ${style.label}`}
          style={MONO}
        >
          {style.text}
        </span>
        <span className="text-[11px] text-[#5B6675]" style={MONO}>
          {flag.rule_id}
        </span>
      </div>
      <p className="text-[13px] leading-relaxed">{flag.message}</p>
      {flag.evidence && (
        <p className="mt-2 border-l-2 border-[#D9DEE6] pl-2 text-[12px] italic leading-relaxed text-[#5B6675]">
          {flag.evidence.length > 180
            ? `${flag.evidence.slice(0, 180)}…`
            : flag.evidence}
        </p>
      )}
    </div>
  );
}

export default function Page() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [showSources, setShowSources] = useState(false);

  // ingestion
  const [file, setFile] = useState<File | null>(null);
  const [ingestDrug, setIngestDrug] = useState("apixaban");
  const [sourceName, setSourceName] = useState("");
  const [sourceType, setSourceType] = useState<SourceType>("publication");
  const [ingesting, setIngesting] = useState(false);
  const [ingestError, setIngestError] = useState<string | null>(null);
  const [ingestResult, setIngestResult] = useState<IngestResponse | null>(null);

  // generation
  const [drug, setDrug] = useState("apixaban");
  const [specialty, setSpecialty] = useState("cardiology");
  const [therapyArea, setTherapyArea] = useState(
    "atrial fibrillation stroke prevention"
  );
  const [stage, setStage] = useState<AdoptionStage>("evaluating");
  const [channel, setChannel] = useState<Channel>("email");
  const [sourceDoc, setSourceDoc] = useState<string>("");

  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GenerateResponse | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  // sign-off
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [deciding, setDeciding] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [decision, setDecision] = useState<DecisionOut | null>(null);

  const refreshState = useCallback(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
    listDocuments()
      .then(setDocuments)
      .catch(() => setDocuments([]));
  }, []);

  useEffect(() => {
    refreshState();
  }, [refreshState]);

  useEffect(() => {
    if (loading || ingesting) {
      setElapsed(0);
      timer.current = setInterval(() => setElapsed((e) => e + 1), 1000);
    } else if (timer.current) {
      clearInterval(timer.current);
    }
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [loading, ingesting]);

  async function handleIngest() {
    if (!file || !sourceName.trim()) return;
    setIngesting(true);
    setIngestError(null);
    setIngestResult(null);
    try {
      const data = await ingestDocument({
        file,
        drug: ingestDrug.trim().toLowerCase(),
        source_name: sourceName.trim(),
        source_type: sourceType,
      });
      setIngestResult(data);
      setSourceDoc(data.document_id);
      setFile(null);
      setSourceName("");
      refreshState();
    } catch (e) {
      setIngestError(e instanceof Error ? e.message : "Ingestion failed.");
    } finally {
      setIngesting(false);
    }
  }

  async function handleGenerate() {
    setLoading(true);
    setError(null);
    setResult(null);
    setDecision(null);
    setDecisionError(null);
    try {
      const data = await generateContent({
        drug,
        profile: {
          specialty,
          therapy_area: therapyArea,
          adoption_stage: stage,
        },
        channel,
        document_id: sourceDoc || null,
      });
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed.");
    } finally {
      setLoading(false);
    }
  }

  async function handleDecision(verdict: "approved" | "rejected") {
    if (!result?.body) return;
    setDeciding(true);
    setDecisionError(null);
    try {
      const recorded = await recordDecision({
        decision: verdict,
        reviewer: reviewer.trim(),
        note: note.trim() || null,
        drug: result.drug,
        profile: {
          specialty,
          therapy_area: therapyArea,
          adoption_stage: stage,
        },
        channel: result.channel,
        subject: result.subject,
        body: result.body,
        claim_ids: result.cited_claims.map((c) => c.id),
      });
      setDecision(recorded);
    } catch (e) {
      setDecisionError(
        e instanceof Error ? e.message : "Could not record the decision."
      );
    } finally {
      setDeciding(false);
    }
  }

  const blockers = result?.flags.filter((f) => f.severity === "blocker") ?? [];
  const advisories = result?.flags.filter((f) => f.severity !== "blocker") ?? [];
  const canDecide = reviewer.trim().length > 0 && !deciding;
  const canIngest = file !== null && sourceName.trim().length > 0 && !ingesting;
  const docsForDrug = documents.filter((d) => d.drug === drug);

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="border-b border-[#D9DEE6] pb-6">
        <h1 className="text-[28px] font-semibold tracking-tight" style={SERIF}>
          HCP Content Engine
        </h1>
        <p className="mt-1 text-[14px] text-[#5B6675]">
          Content grounded in an approved claim set, checked before a human
          signs off.
        </p>
        {health && (
          <div
            className="mt-4 flex flex-wrap gap-x-6 gap-y-1 text-[11px] text-[#5B6675]"
            style={MONO}
          >
            <span>{health.claims_loaded} claims</span>
            <span>{health.unverified_claims} awaiting verification</span>
            <span>{health.active_rules.join(" · ")}</span>
          </div>
        )}
      </header>

      {/* ---------------- Knowledge base ---------------- */}

      <section className="mt-8 border border-[#D9DEE6] bg-white">
        <button
          onClick={() => setShowSources((s) => !s)}
          className="flex w-full items-center justify-between px-5 py-3 text-left transition-colors hover:bg-[#F7F8FA]"
        >
          <span
            className="text-[11px] uppercase tracking-wider text-[#5B6675]"
            style={MONO}
          >
            Knowledge base — {documents.length} source
            {documents.length === 1 ? "" : "s"}
          </span>
          <span className="text-[14px] text-[#5B6675]">
            {showSources ? "−" : "+"}
          </span>
        </button>

        {showSources && (
          <div className="border-t border-[#D9DEE6] px-5 py-5">
            {documents.length > 0 && (
              <ul className="mb-6 space-y-2">
                {documents.map((d) => (
                  <li
                    key={d.document_id}
                    className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-[#F0F2F5] pb-2 text-[13px] last:border-0"
                  >
                    <SourceBadge type={d.source_type} />
                    <span className="flex-1">{d.source_name}</span>
                    <span className="text-[11px] text-[#5B6675]" style={MONO}>
                      {d.drug}
                    </span>
                    <span className="text-[11px] text-[#5B6675]" style={MONO}>
                      {d.claim_count} claims
                    </span>
                    <span
                      className={`text-[11px] ${
                        d.verified_count === d.claim_count
                          ? "text-[#14624A]"
                          : "text-[#8A5A00]"
                      }`}
                      style={MONO}
                    >
                      {d.verified_count}/{d.claim_count} verified
                    </span>
                  </li>
                ))}
              </ul>
            )}

            <p
              className="mb-3 text-[11px] uppercase tracking-wider text-[#5B6675]"
              style={MONO}
            >
              Add a source
            </p>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="PDF">
                <input
                  type="file"
                  accept=".pdf,application/pdf"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="w-full text-[12px] text-[#5B6675] file:mr-2 file:border file:border-[#D9DEE6] file:bg-white file:px-2 file:py-1 file:text-[12px] file:text-[#16202E]"
                />
              </Field>
              <Field label="Drug">
                <input
                  className={INPUT_CLASS}
                  value={ingestDrug}
                  onChange={(e) => setIngestDrug(e.target.value)}
                />
              </Field>
              <Field label="Source name">
                <input
                  className={INPUT_CLASS}
                  placeholder="e.g. ARISTOTLE publication"
                  value={sourceName}
                  onChange={(e) => setSourceName(e.target.value)}
                />
              </Field>
              <Field label="Source type">
                <select
                  className={`${INPUT_CLASS} bg-white`}
                  value={sourceType}
                  onChange={(e) => setSourceType(e.target.value as SourceType)}
                >
                  {SOURCE_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            <button
              onClick={handleIngest}
              disabled={!canIngest}
              className="mt-4 bg-[#16202E] px-4 py-2 text-[14px] text-white transition-colors hover:bg-[#2A3646] disabled:bg-[#9AA5B4]"
            >
              {ingesting ? `Extracting… ${elapsed}s` : "Ingest document"}
            </button>

            {ingesting && (
              <p className="mt-3 text-[13px] text-[#5B6675]">
                Reading the PDF and extracting candidate claims. One model call
                per chunk — this takes a few minutes on a local model.
              </p>
            )}

            {ingestError && (
              <p className="mt-3 border-l-2 border-[#B3261E] pl-2 text-[13px] leading-relaxed text-[#B3261E]">
                {ingestError}
              </p>
            )}

            {ingestResult && (
              <div className="mt-4 border border-[#D9DEE6] bg-[#F7F8FA] p-4">
                <p className="text-[13px] font-medium">
                  Extracted {ingestResult.claims_extracted} candidate claim
                  {ingestResult.claims_extracted === 1 ? "" : "s"} from{" "}
                  {ingestResult.source_name}
                </p>
                <p className="mt-1 text-[12px] leading-relaxed text-[#5B6675]">
                  All are unverified. A reviewer must confirm each against the
                  source document before it can be relied on. This document is
                  now selected below as the grounding source.
                </p>
                <ul className="mt-3 space-y-2">
                  {ingestResult.claims.slice(0, 5).map((c) => (
                    <li key={c.id} className="flex gap-3 text-[12px]">
                      <span
                        className="shrink-0 text-[11px] text-[#5B6675]"
                        style={MONO}
                      >
                        {c.id}
                      </span>
                      <span className="flex-1 leading-relaxed">
                        <span
                          className={
                            c.is_risk_side
                              ? "text-[#B3261E]"
                              : "text-[#5B6675]"
                          }
                          style={MONO}
                        >
                          {c.section}
                          {c.page ? ` · p.${c.page}` : ""}
                        </span>
                        <span className="mt-0.5 block">{c.text}</span>
                      </span>
                    </li>
                  ))}
                </ul>
                {ingestResult.claims.length > 5 && (
                  <p className="mt-2 text-[11px] text-[#5B6675]" style={MONO}>
                    + {ingestResult.claims.length - 5} more
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </section>

      {/* ---------------- Generate ---------------- */}

      <section className="mt-6 grid gap-4 border border-[#D9DEE6] bg-white p-5 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Drug">
          <input
            className={INPUT_CLASS}
            value={drug}
            onChange={(e) => setDrug(e.target.value)}
          />
        </Field>
        <Field label="Specialty">
          <input
            className={INPUT_CLASS}
            value={specialty}
            onChange={(e) => setSpecialty(e.target.value)}
          />
        </Field>
        <Field label="Therapy area">
          <input
            className={INPUT_CLASS}
            value={therapyArea}
            onChange={(e) => setTherapyArea(e.target.value)}
          />
        </Field>
        <Field label="Adoption stage">
          <select
            className={`${INPUT_CLASS} bg-white`}
            value={stage}
            onChange={(e) => setStage(e.target.value as AdoptionStage)}
          >
            {ADOPTION_STAGES.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Channel">
          <select
            className={`${INPUT_CLASS} bg-white`}
            value={channel}
            onChange={(e) => setChannel(e.target.value as Channel)}
          >
            {CHANNELS.map((c) => (
              <option key={c} value={c}>
                {c.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Ground in">
          <select
            className={`${INPUT_CLASS} bg-white`}
            value={sourceDoc}
            onChange={(e) => setSourceDoc(e.target.value)}
          >
            <option value="">All sources</option>
            {docsForDrug.map((d) => (
              <option key={d.document_id} value={d.document_id}>
                {d.source_name}
              </option>
            ))}
          </select>
        </Field>
        <div className="flex items-end lg:col-start-3">
          <button
            onClick={handleGenerate}
            disabled={loading || ingesting}
            className="w-full bg-[#16202E] px-4 py-2 text-[14px] text-white transition-colors hover:bg-[#2A3646] disabled:bg-[#9AA5B4]"
          >
            {loading ? `Generating… ${elapsed}s` : "Generate draft"}
          </button>
        </div>
      </section>

      {loading && (
        <p className="mt-4 text-[13px] text-[#5B6675]">
          Retrieving claims, drafting, and running four compliance rules. This
          usually takes 30–60 seconds on a local model.
        </p>
      )}

      {error && (
        <div className="mt-6 border-l-4 border-[#B3261E] bg-white p-4 text-[14px]">
          <p className="font-medium">Generation failed</p>
          <p className="mt-1 text-[#5B6675]">{error}</p>
          <p className="mt-2 text-[13px] text-[#5B6675]">
            Check that the API is running on port 8000 and Ollama is serving.
          </p>
        </div>
      )}

      {result && (
        <>
          <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-2 border border-[#D9DEE6] bg-white px-5 py-3">
            <span
              className={`text-[13px] font-medium ${
                result.passed ? "text-[#14624A]" : "text-[#B3261E]"
              }`}
            >
              {result.passed
                ? "Passed automated checks — awaiting human approval"
                : "Blocked — cannot be sent"}
            </span>
            <span className="text-[11px] text-[#5B6675]" style={MONO}>
              {result.attempts} attempt{result.attempts === 1 ? "" : "s"} ·{" "}
              {blockers.length} blocker · {advisories.length} advisory
            </span>
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_360px]">
            <article className="border border-[#D9DEE6] bg-white p-7">
              {result.subject && (
                <>
                  <p
                    className="text-[11px] uppercase tracking-wider text-[#5B6675]"
                    style={MONO}
                  >
                    Subject
                  </p>
                  <h2
                    className="mb-5 mt-1 text-[20px] font-semibold"
                    style={SERIF}
                  >
                    {result.subject}
                  </h2>
                </>
              )}
              <div style={SERIF}>
                {result.body && (
                  <AnnotatedBody
                    body={result.body}
                    claims={result.cited_claims}
                  />
                )}
              </div>

              <div className="mt-8 border-t border-[#D9DEE6] pt-5">
                <p
                  className="mb-3 text-[11px] uppercase tracking-wider text-[#5B6675]"
                  style={MONO}
                >
                  Sources — every statement traces here
                </p>
                <ul className="space-y-3">
                  {result.cited_claims.map((c) => (
                    <li key={c.id} className="flex gap-3 text-[13px]">
                      <span
                        className="shrink-0 text-[11px] text-[#5B6675]"
                        style={MONO}
                      >
                        {c.id}
                      </span>
                      <span className="flex-1">
                        <span className="flex flex-wrap items-center gap-2">
                          <SourceBadge type={c.source_type} />
                          <span
                            className={
                              c.is_risk_side
                                ? "text-[#B3261E]"
                                : "text-[#5B6675]"
                            }
                            style={MONO}
                          >
                            {c.section}
                            {c.page ? ` · p.${c.page}` : ""}
                          </span>
                        </span>
                        <span className="mt-1 block leading-relaxed">
                          {c.text}
                        </span>
                        {!c.verified && (
                          <span className="mt-1 inline-block text-[11px] text-[#8A5A00]">
                            not yet human-verified
                          </span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </article>

            <aside className="space-y-3">
              <p
                className="text-[11px] uppercase tracking-wider text-[#5B6675]"
                style={MONO}
              >
                Review margin
              </p>
              {result.flags.length === 0 && (
                <p className="border border-[#D9DEE6] bg-white p-4 text-[13px] text-[#5B6675]">
                  No findings.
                </p>
              )}
              {result.flags.map((f, i) => (
                <FlagCard key={i} flag={f} />
              ))}

              <div className="border border-[#D9DEE6] bg-white p-4">
                <p
                  className="mb-2 text-[11px] uppercase tracking-wider text-[#5B6675]"
                  style={MONO}
                >
                  Run log
                </p>
                <ol className="space-y-1.5 text-[12px] leading-relaxed text-[#5B6675]">
                  {result.history.map((h, i) => (
                    <li key={i}>{h}</li>
                  ))}
                </ol>
              </div>

              {decision ? (
                <div className="border border-[#D9DEE6] bg-white p-4">
                  <p
                    className="mb-2 text-[11px] uppercase tracking-wider text-[#5B6675]"
                    style={MONO}
                  >
                    Recorded
                  </p>
                  <p
                    className={`text-[14px] font-medium ${
                      decision.decision === "approved"
                        ? "text-[#14624A]"
                        : "text-[#B3261E]"
                    }`}
                  >
                    {decision.decision === "approved" ? "Approved" : "Rejected"}{" "}
                    by {decision.reviewer}
                  </p>
                  {decision.note && (
                    <p className="mt-2 text-[13px] leading-relaxed text-[#5B6675]">
                      {decision.note}
                    </p>
                  )}
                  <p className="mt-3 text-[11px] text-[#5B6675]" style={MONO}>
                    {new Date(decision.created_at).toLocaleString()}
                  </p>
                  <p
                    className="mt-1 break-all text-[11px] text-[#5B6675]"
                    style={MONO}
                  >
                    {decision.id}
                  </p>
                  <p className="mt-3 text-[12px] leading-relaxed text-[#5B6675]">
                    This record cannot be edited. A change of mind is recorded
                    as a new decision.
                  </p>
                </div>
              ) : (
                <div className="border border-[#D9DEE6] bg-white p-4">
                  <p
                    className="mb-3 text-[11px] uppercase tracking-wider text-[#5B6675]"
                    style={MONO}
                  >
                    Sign-off
                  </p>
                  <Field label="Reviewer">
                    <input
                      className={INPUT_CLASS}
                      placeholder="Your name"
                      value={reviewer}
                      onChange={(e) => setReviewer(e.target.value)}
                    />
                  </Field>
                  <div className="mt-3">
                    <Field label="Note (optional)">
                      <textarea
                        rows={3}
                        className={`${INPUT_CLASS} resize-none`}
                        placeholder="Reasoning for the record"
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                      />
                    </Field>
                  </div>

                  {decisionError && (
                    <p className="mt-3 border-l-2 border-[#B3261E] pl-2 text-[12px] leading-relaxed text-[#B3261E]">
                      {decisionError}
                    </p>
                  )}

                  <div className="mt-4 flex gap-2">
                    <button
                      onClick={() => handleDecision("approved")}
                      disabled={!canDecide || !result.passed}
                      className="flex-1 bg-[#14624A] px-3 py-2 text-[13px] text-white transition-colors hover:bg-[#1A7A5A] disabled:bg-[#9AA5B4]"
                    >
                      {deciding ? "Saving…" : "Approve"}
                    </button>
                    <button
                      onClick={() => handleDecision("rejected")}
                      disabled={!canDecide}
                      className="flex-1 border border-[#D9DEE6] bg-white px-3 py-2 text-[13px] transition-colors hover:bg-[#F7F8FA] disabled:text-[#9AA5B4]"
                    >
                      Reject
                    </button>
                  </div>

                  {!result.passed && (
                    <p className="mt-2 text-[12px] leading-relaxed text-[#5B6675]">
                      Approval is unavailable while blocking issues remain.
                    </p>
                  )}
                </div>
              )}
            </aside>
          </div>
        </>
      )}
    </main>
  );
}