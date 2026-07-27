# 合同评审 API 契约

所有接口（登录接口除外）都需要 `Authorization: Bearer <token>`；SSE 也支持 `access_token` 查询参数。

## 身份与基础能力

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/auth/login` | 登录并返回 Bearer Token |
| `GET` | `/api/auth/me` | 当前用户和权限 |
| `GET` | `/api/health` | 模型与安全运行状态 |
| `GET` | `/api/rules` | 合同底限规则库 |
| `GET` | `/api/reviewers` | 可被指派的启用信用审核专员 |

## 信审（前置）

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/credit/decisions` | 可供合同绑定的、当前已生效信审版本 |
| `GET` | `/api/credit/cases` | 信审案件及历史版本 |
| `POST` | `/api/credit/cases` | 业务申请人发起、信用审核专员也可代建的信审草稿 |
| `PATCH` | `/api/credit/cases/{case_id}` | 信用审核专员评估并修改草稿信用条件 |
| `POST` | `/api/credit/cases/{case_id}/submit` | 信用审核专员提交至财务审批主管复核 |
| `POST` | `/api/credit/cases/{case_id}/decision` | 主管复核通过后转集团财务总监最终批核；任一层可拒绝 |

`POST /api/review` 和批量评审必须带 `credit_case_id`，且该版本必须为当前已生效状态。合同导出再次校验该绑定，并拒绝任何 `CREDIT_*` 越界项。

## 案件与审查

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/review` | 上传单份合同并创建案件 |
| `POST` | `/api/review/batch` | 批量上传合同 |
| `GET` | `/api/stream/{job_id}` | 订阅 AI 审查步骤与结果 |
| `GET` | `/api/cases` | 获取团队案件台账；业务人员只看本人案件 |
| `PATCH` | `/api/cases/{job_id}` | 信用审核专员/管理角色更新负责人、优先级、截止时间或状态 |
| `GET` | `/api/history/{job_id}` | 获取完整审查报告与风险处置记录 |
| `GET` | `/api/stats` | 获取工作台统计 |

上传表单支持 `assignee_id`、`priority`（`low`/`normal`/`high`/`urgent`）、`due_at`（Unix 秒）和 `request_note`。

## 风险与交付

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/contracts/cases/{job_id}/findings` | 风险发现与当前处置状态 |
| `POST` | `/api/contracts/cases/{job_id}/findings/{finding_id}/actions` | 采纳、忽略或编辑后采纳，并写入审计 |
| `GET` | `/api/export/{job_id}?mode=revised\|plain\|bilingual&lang=` | 导出 Word：修订稿 / 原文版 / 双语对照（bilingual 需先翻译） |
| `POST` | `/api/translate/{job_id}` | 启动条款翻译（结果持久化；`force=true` 可重跑） |
| `GET` | `/api/translate/{job_id}?lang=` | 读取已持久化翻译 |
| `GET` | `/api/translate/{job_id}/list` | 列出该案件已有翻译语言 |
| `GET` | `/api/translate/stream/{tfid}` | 翻译任务 SSE |
| `POST` | `/api/cases/{job_id}/attachments` | 上传同案附件（annex） |
| `GET` | `/api/cases/{job_id}/attachments` | 附件列表与预览 |
| `GET` | `/api/cases/{job_id}/attachments/{file_id}/download` | 下载附件 |
| `POST` | `/api/integrations/oa/flow` | 创建泛微 OA Mock 流程（可带 `job_id`） |
| `GET` | `/api/integrations/oa/flow/{flow_id}` | 查询 OA 流程 |
| `POST` | `/api/integrations/oa/flow/{flow_id}/decision` | 角色决策 |
| `POST` | `/api/integrations/oa/flow/{flow_id}/batch-update` | 批量挂载已采纳建议 |
| `POST` | `/api/integrations/crm/credit-hooks` | CRM 预留端口：推送客户并可选创建信审草稿 |
| `GET` | `/api/integrations/crm/credit-hooks` | 列出 CRM hook |
| `GET` | `/api/integrations/crm/credit-hooks/{hook_id}` | 查询单个 hook |
