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

export type CreditConditions = { max_credit_amount:number; currency:string; max_payment_days:number; min_prepayment_ratio:number; allowed_payment_methods:string[]; allow_vmi_jit:boolean; valid_from?:number; valid_to?:number; available_credit_amount?:number; exposure_at_assessment?:number }
export type CreditCase = { case_id:string; customer_name:string; version:number; status:'draft'|'returned_to_business'|'returned_to_reviewer'|'pending_director'|'pending_final'|'approved'|'rejected'|'superseded'; conditions:CreditConditions; request_note:string; business_type?:string; director_note?:string; decision_note:string; return_note?:string; return_target?:'business'|'reviewer'|''; returned_by?:string; returned_at?:number; assessment_id?:string; assessment_snapshot?:any; route_version?:string; route_snapshot?:{version?:string;requires_final?:boolean;reasons?:string[];config?:any}; review_mode?:'agent_recommended'|'reviewer_adjusted'|'manual_override'|''; reviewer_note?:string; reviewed_by?:string; reviewed_at?:number; created_at:number; submitted_at?:number; director_at?:number; decided_at?:number }
export type CreditRouteVersion = {version:string;status:'draft'|'published'|'archived';config:{director_required:boolean;final_threshold_amount:number;final_threshold_payment_days:number;final_threshold_prepayment_ratio:number;final_on_manual_override:boolean;final_on_acceptance_bill:boolean;final_on_vmi_jit:boolean};created_at:number;published_at?:number}
export type CreditDocument = { document_id:string; case_id:string; document_type:'financial_report'|'credit_report'|'trade_history'|'application'|'approval_evidence'|'other'; original_name:string; content_hash:string; uploaded_by?:string; created_at:number; text_status?:'ready'|'partial'|'failed'; text_parser_version?:string; text_updated_at?:number; text_error?:string; text_record_count?:number }
export type CreditExposure = { snapshot_id?:string; source?:string; captured_at?:number; payload?:{current_receivables:number;booked_order_amount:number;overdue_amount:number;overdue_days:number;currency?:string;as_of?:number;note?:string}|null }
export type CreditAssessment = { assessment_id?:string; case_id?:string; status:'none'|'running'|'done'|'error'; model_version?:string; policy_version?:string; report?:any; evidence?:any[]; error?:string; created_at?:number; completed_at?:number }
export type ReviewRequest = { business_type?: string; credit_case_id?:string; parent_job_id?: string; assignee_id?: string; priority?: string; due_at?: number; request_note?: string; case_id?:string; document_role?:string }
export type TeamMember = { id: string; display_name: string; role: string }
export type CaseItem = {
  case_id: string; job_id: string; filename: string; workflow_status: string; review_status: string
  priority: 'low'|'normal'|'high'|'urgent'; due_at?: number; request_note?: string; created_at: number; updated_at: number
  assigned_to?: string; assignee_name?: string; requester_name?: string; overall_level?: string; n_clauses: number; n_risks: number; high: number; mid: number; low: number
}

export type WorkItem = { task_id:string; case_id:string; target_id?:string; source_type?:'contract'|'credit'; task_type:string; title:string; detail:string; status:string; due_at?:number; created_at:number; customer_name:string; current_stage:string; priority:string; filename?:string; business_type?:string }
export type CaseDocument = { document_id:string; job_id?:string; original_name:string; document_role:string; version_label:string; review_status?:string; overall_level?:string; n_risks?:number; high?:number; mid?:number; low?:number; created_at:number }
export type CaseEvent = { event_id:string; event_type:string; message:string; actor_id?:string; created_at:number }
export type CaseCenterItem = { case_id:string; customer_name:string; business_type:string; workflow_status:string; current_stage:string; priority:string; due_at?:number; request_note?:string; created_at:number; updated_at:number; requester_name?:string; assignee_name?:string; filename?:string; job_id?:string; overall_level?:string; document_count:number; open_tasks:number; credit_case_id?:string }
export type CaseCenterDetail = CaseCenterItem & { assigned_to?:string; documents:CaseDocument[]; tasks:WorkItem[]; events:CaseEvent[] }

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
