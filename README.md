# ContractGuard · 火鸟黑客松（东江集团 · 信审与合同评审）

面向制造企业法务/财务场景的 **AI 智能信审与合同评审** 工作台：信审前置决定商业边界，合同后置做底限审查与协作交付。

## 仓库结构

```text
.
├─ backend/                # FastAPI + LangGraph
├─ frontend/               # React + Ant Design + Vite
├─ docs/                   # 命题、架构、接口、演示（已分类）
│  ├─ 00-命题与数据/
│  ├─ 01-产品与架构/
│  ├─ 02-接口与验收/
│  └─ 03-演示与交付/
├─ dev.ps1                 # 一键启动前后端
└─ README.md
```

文档总索引见 [docs/README.md](./docs/README.md)。

## 快速启动

```powershell
copy backend\.env.example backend\.env
# 填写 AUTH_SECRET / DATA_ENCRYPTION_KEY / LLM_API_BASE / LLM_API_KEY / LLM_MODEL
.\dev.ps1
```

浏览器打开 `http://127.0.0.1:5173`。

生成加密密钥示例：

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

本地演示管理员由 `backend/.env` 的 `INITIAL_ADMIN_*` 决定（正式环境务必改密；`.env` 不入库）。

## 能力摘要

- 合同：解析（DOCX/PDF/XLSX/TXT/PNG）→ 本地脱敏 → 字段抽取 → **词法规则候选** → LLM 研判 → 确定性底限 + 信审越界校验  
- 协作：案件台账、审批例外、待补材料、风险采纳、版本对比  
- 定制演示：CRM Mock 端口、泛微 OA Mock、多语言翻译与双语导出、同案附件、修订/原文/双语三模式导出  
- **不做** 16 条底限的 per-clause 向量 RAG（封闭规则集用确定性门控更稳）  
- 信审 **测算模型**（年报/评级自动授信）可独立演进；合同侧只消费「已生效」信审版本  

## 管理员系统设置

- 主审查模型 OpenAI 兼容地址 / 模型名 / API Key  
- 合同脱敏开关与本地智能脱敏模型  
- 主模型连接测试  

配置写入本机 `backend/.env`，密钥只显示「已配置」。保存后重启后端生效。

## 验证

```powershell
cd backend
python scripts/test_security_workflow.py
python scripts/test_context_budget.py
python scripts/test_mask_fast_path.py
cd ..\frontend
npm run build
```

## 数据与合规

命题与数据包仅限本次黑客松开发使用；赛事结束后删除企业原始数据。详见 `docs/00-命题与数据/`。
