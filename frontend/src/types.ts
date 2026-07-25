export type Risk = {
  clause_id: string; page: number; source_ref?: string; rule_id: string; rule_baseline: string
  dim: string; evidence: string; suggestion: string; severity: 'high'|'mid'|'low'
  level: string; numeric_note: string
  facts?: Record<string, any>; approval_required?: string; decision?: string
  finding_id?: string; action_status?: string; rule_version?: string
}
export type Clause = { id: string; text: string; start_page: number; end_page: number; source_ref?: string }
export type Report = {
  filename: string; summary: Summary; contract_fields: any; clauses: Clause[]
  risks: Risk[]; review_hints?: Risk[]; steps: string[]; masked_entities: number
  credit_decision?: { case_id:string; customer_name:string; version:number; conditions:CreditConditions }
  _job_id?: string
  review_scope?: { mode?:string; changed_clause_ids?:string[]; context_clause_ids?:string[]; total_clauses?:number }
}
export type Summary = {
  n_clauses: number; n_risks: number; high: number; mid: number; low: number
  n_needs_review?: number; overall_level: string; contract_fields?: any
}
export type HistoryItem = {
  id: string; filename: string; status: string; created_at: number; finished_at: number
  overall_level: string; n_clauses: number; n_risks: number; high: number; mid: number; low: number
  masked_entities: number; our_party: string; business_type: string
}
export type RuleItem = { id: string; dim: string; baseline: string; check: string; severity: string; applies_to?: string[]; approval_role?: string; template?: string }
export type RuleVersion = { version:string; status:'draft'|'published'|'archived'; created_at:number; published_at?:number }
export type ApprovalItem = { approval_id:string; finding_id:string; required_role:string; status:string; decision_note:string; created_at:number; decided_at?:number }
export type MaterialRequest = { request_id:string; finding_id?:string; title:string; detail:string; status:string; created_at:number; resolved_at?:number; files?:{file_id:string;original_name:string;created_at:number}[] }
export type KnowledgeItem = { case_id:string; rule_id:string; business_type?:string; source_clause:string; source_ref?:string; evidence?:string; suggested_text?:string; outcome:string; created_at:number }
export type Stats = {
  total: number; done: number; blocked: number; high: number; mid: number
  clauses: number; rules_freq: Record<string, number>; my_open: number; unassigned: number; due_soon: number
}
export type HealthInfo = { ollama: boolean; llm: boolean }

export type CreditConditions = { max_credit_amount:number; currency:string; max_payment_days:number; min_prepayment_ratio:number; allowed_payment_methods:string[]; allow_vmi_jit:boolean; valid_from?:number; valid_to?:number }
export type CreditCase = { case_id:string; customer_name:string; version:number; status:'draft'|'pending_approval'|'approved'|'rejected'|'superseded'; conditions:CreditConditions; request_note:string; decision_note:string; created_at:number; submitted_at?:number; decided_at?:number }
export type ReviewRequest = { business_type?: string; credit_case_id?:string; parent_job_id?: string; assignee_id?: string; priority?: string; due_at?: number; request_note?: string }
export type TeamMember = { id: string; display_name: string; role: string }
export type CaseItem = {
  case_id: string; job_id: string; filename: string; workflow_status: string; review_status: string
  priority: 'low'|'normal'|'high'|'urgent'; due_at?: number; request_note?: string; created_at: number; updated_at: number
  assigned_to?: string; assignee_name?: string; requester_name?: string; overall_level?: string; n_clauses: number; n_risks: number; high: number; mid: number; low: number
}

export const sevColor: Record<string,string> = { high: 'red', mid: 'orange', low: 'blue' }

/* ============= 翻译 / 批量 ============= */
export type TranslateItem = {
  clause_id: string; original: string; translated: string
  masked_original?: string; translated_masked?: string; mask_restored?: boolean
}
export type TranslateResult = {
  target_lang: string; translated: TranslateItem[]
  contract_fields_translated: Record<string, any>
}
export type BatchJob = { job_id: string; filename: string }
