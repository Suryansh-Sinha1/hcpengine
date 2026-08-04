"use client";

import { useEffect, useRef, useState } from "react";
import {
  generateContent,
  getHealth,
  type AdoptionStage,
  type Channel,
  type ClaimOut,
  type ComplianceFlag,
  type GenerateResponse,
  type HealthResponse,
} from "@/lib/api";

const SEVERITY_STYLE: Record<string, { bar: string; label: string; text: string }> = {
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

/** Renders [apx-ind-001] markers in the body as inline citation chips. */
function AnnotatedBody({ body, claims }: { body: string; claims: ClaimOut[] }) {
  const byId = new Map(claims.map((c) => [c.id, c]));
  const parts = body.split(/(\[[a-z0-9-]+\])/gi);

  return (
    <p className="whitespace-pre-wrap leading-[1.75] text-[17px]">
      {parts.map((part, i) => {
        const match = part.match(/^\[([a-z0-9-]+)\]$/i);
        const claim = match ? byId.get(match[1]) : undefined;
        if (!claim) return <span key={i}>{part}</span>;
        return (
          <span
            key={i}
            title={`${claim.section} — ${claim.text}`}
            className="mx-0.5 rounded-sm border border-[#D9DEE6] bg-white px-1 py-0.5 align-middle text-[11px] text-[#5B6675] cursor-help"
            style={{ fontFamily: "var(--font-mono)" }}
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
    <div className="relative border border-[#D9DEE6] bg-white pl-4 pr-4 py-3">
      <span className={`absolute left-0 top-0 h-full w-1 ${style.bar}`} />
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <span
          className={`text-[11px] uppercase tracking-wider ${style.label}`}
          style={{ fontFamily: "var(--font-mono)" }}
        >
          {style.text}
        </span>
        <span
          className="text-[11px] text-[#5B6675]"
          style={{ fontFamily: "var(--font-mono)" }}
        >
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
  const [drug, setDrug] = useState("apixaban");
  const [specialty, setSpecialty] = useState("cardiology");
  const [therapyArea, setTherapyArea] = useState(
    "atrial fibrillation stroke prevention"
  );
  const [stage, setStage] = useState<AdoptionStage>("evaluating");
  const [channel, setChannel] = useState<Channel>("email");

  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GenerateResponse | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    if (loading) {
      setElapsed(0);
      timer.current = setInterval(() => setElapsed((e) => e + 1), 1000);
    } else if (timer.current) {
      clearInterval(timer.current);
    }
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [loading]);

  async function handleGenerate() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await generateContent({
        drug,
        profile: {
          specialty,
          therapy_area: therapyArea,
          adoption_stage: stage,
        },
        channel,
      });
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed.");
    } finally {
      setLoading(false);
    }
  }

  const blockers = result?.flags.filter((f) => f.severity === "blocker") ?? [];
  const advisories = result?.flags.filter((f) => f.severity !== "blocker") ?? [];

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="border-b border-[#D9DEE6] pb-6">
        <h1
          className="text-[28px] font-semibold tracking-tight"
          style={{ fontFamily: "var(--font-serif)" }}
        >
          HCP Content Engine
        </h1>
        <p className="mt-1 text-[14px] text-[#5B6675]">
          Content grounded in an approved claim set, checked before a human
          signs off.
        </p>
        {health && (
          <div
            className="mt-4 flex flex-wrap gap-x-6 gap-y-1 text-[11px] text-[#5B6675]"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            <span>{health.claims_loaded} claims</span>
            <span>{health.unverified_claims} awaiting verification</span>
            <span>{health.active_rules.join(" · ")}</span>
          </div>
        )}
      </header>

      <section className="mt-8 grid gap-4 border border-[#D9DEE6] bg-white p-5 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Drug">
          <input
            className="w-full border border-[#D9DEE6] px-2 py-1.5 text-[14px] outline-none focus:border-[#16202E]"
            value={drug}
            onChange={(e) => setDrug(e.target.value)}
          />
        </Field>
        <Field label="Specialty">
          <input
            className="w-full border border-[#D9DEE6] px-2 py-1.5 text-[14px] outline-none focus:border-[#16202E]"
            value={specialty}
            onChange={(e) => setSpecialty(e.target.value)}
          />
        </Field>
        <Field label="Therapy area">
          <input
            className="w-full border border-[#D9DEE6] px-2 py-1.5 text-[14px] outline-none focus:border-[#16202E]"
            value={therapyArea}
            onChange={(e) => setTherapyArea(e.target.value)}
          />
        </Field>
        <Field label="Adoption stage">
          <select
            className="w-full border border-[#D9DEE6] bg-white px-2 py-1.5 text-[14px] outline-none focus:border-[#16202E]"
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
            className="w-full border border-[#D9DEE6] bg-white px-2 py-1.5 text-[14px] outline-none focus:border-[#16202E]"
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
        <div className="flex items-end">
          <button
            onClick={handleGenerate}
            disabled={loading}
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
            <span
              className="text-[11px] text-[#5B6675]"
              style={{ fontFamily: "var(--font-mono)" }}
            >
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
                    style={{ fontFamily: "var(--font-mono)" }}
                  >
                    Subject
                  </p>
                  <h2
                    className="mt-1 mb-5 text-[20px] font-semibold"
                    style={{ fontFamily: "var(--font-serif)" }}
                  >
                    {result.subject}
                  </h2>
                </>
              )}
              <div style={{ fontFamily: "var(--font-serif)" }}>
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
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  Sources — every statement traces here
                </p>
                <ul className="space-y-3">
                  {result.cited_claims.map((c) => (
                    <li key={c.id} className="flex gap-3 text-[13px]">
                      <span
                        className="shrink-0 text-[11px] text-[#5B6675]"
                        style={{ fontFamily: "var(--font-mono)" }}
                      >
                        {c.id}
                      </span>
                      <span className="flex-1">
                        <span
                          className={
                            c.is_risk_side
                              ? "text-[#B3261E]"
                              : "text-[#5B6675]"
                          }
                          style={{ fontFamily: "var(--font-mono)" }}
                        >
                          {c.section}
                        </span>
                        <span className="mt-0.5 block leading-relaxed">
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
                style={{ fontFamily: "var(--font-mono)" }}
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
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  Run log
                </p>
                <ol className="space-y-1.5 text-[12px] leading-relaxed text-[#5B6675]">
                  {result.history.map((h, i) => (
                    <li key={i}>{h}</li>
                  ))}
                </ol>
              </div>

              <div className="flex gap-2 pt-1">
                <button
                  disabled={!result.passed}
                  className="flex-1 bg-[#14624A] px-3 py-2 text-[13px] text-white disabled:bg-[#9AA5B4]"
                >
                  Approve
                </button>
                <button className="flex-1 border border-[#D9DEE6] bg-white px-3 py-2 text-[13px]">
                  Reject
                </button>
              </div>
            </aside>
          </div>
        </>
      )}
    </main>
  );
}

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
        style={{ fontFamily: "var(--font-mono)" }}
      >
        {label}
      </span>
      {children}
    </label>
  );
}