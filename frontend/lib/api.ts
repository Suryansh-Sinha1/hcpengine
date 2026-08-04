export type Severity = "blocker" | "warning" | "info";
export type Channel = "email" | "detail_aid" | "follow_up";
export type AdoptionStage =
  | "unaware"
  | "aware"
  | "evaluating"
  | "occasional_prescriber"
  | "advocate";

export interface HCPProfile {
  specialty: string;
  therapy_area: string;
  adoption_stage: AdoptionStage;
}

export interface ClaimOut {
  id: string;
  drug: string;
  text: string;
  claim_type: string;
  source: string;
  section: string;
  verified: boolean;
  is_risk_side: boolean;
}

export interface ComplianceFlag {
  rule_id: string;
  severity: Severity;
  message: string;
  evidence: string | null;
  suggestion: string | null;
}

export interface GenerateResponse {
  status: string;
  passed: boolean;
  drug: string;
  channel: Channel;
  subject: string | null;
  body: string | null;
  cited_claims: ClaimOut[];
  flags: ComplianceFlag[];
  attempts: number;
  history: string[];
}

export interface DecisionOut {
  id: string;
  created_at: string;
  decision: string;
  reviewer: string;
  note: string | null;
  drug: string;
  channel: string;
  specialty: string;
  therapy_area: string;
  adoption_stage: string;
  subject: string | null;
  body: string;
  claim_ids: string[];
  flags_at_decision: ComplianceFlag[];
  passed_automated: boolean;
}

export interface HealthResponse {
  status: string;
  claims_loaded: number;
  drugs: string[];
  unverified_claims: number;
  active_rules: string[];
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // response had no JSON body; keep the status text
    }
    throw new Error(detail);
  }

  return res.json() as Promise<T>;
}

export function getHealth() {
  return request<HealthResponse>("/health");
}

export function generateContent(input: {
  drug: string;
  profile: HCPProfile;
  channel: Channel;
}) {
  return request<GenerateResponse>("/generate", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function recordDecision(input: {
  decision: "approved" | "rejected";
  reviewer: string;
  note: string | null;
  drug: string;
  profile: HCPProfile;
  channel: Channel;
  subject: string | null;
  body: string;
  claim_ids: string[];
}) {
  return request<DecisionOut>("/decisions", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listDecisions(limit = 50) {
  return request<DecisionOut[]>(`/decisions?limit=${limit}`);
}