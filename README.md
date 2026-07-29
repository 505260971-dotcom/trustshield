# ContractGuard · 火鸟黑客松（东江集团 · 信审与合同评审）

面向制造企业财务信用与合同风险场景的 **AI 智能信审与合同评审** 工作台：信审前置决定商业边界，合同后置做底限审查与协作交付。

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
# 只填写启动级安全参数：AUTH_SECRET / DATA_ENCRYPTION_KEY / INITIAL_ADMIN_*
.\dev.ps1
```

浏览器打开 `http://127.0.0.1:5173`。

`dev.ps1` 会在两个独立 PowerShell 窗口启动 FastAPI 和 Vite；传入 `-NoBrowser` 可只启动服务而不自动打开浏览器。首次运行前分别在 `backend/`、`frontend/` 安装 Python 与 Node 依赖。

生成加密密钥示例：

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

本地演示管理员由 `backend/.env` 的 `INITIAL_ADMIN_*` 决定（正式环境务必改密；`.env` 不入库）。模型 URL、模型名和 API Key 不写入 `.env`，首次升级时会迁移至 `backend/data/config.json`，随后由管理员在「系统设置」维护。

## 能力摘要

- 合同：解析（DOCX/PDF/XLSX/TXT/PNG）→ 本地脱敏 → 字段抽取 → **词法规则候选** → LLM 研判 → 确定性底限 + 信审越界校验  
- 协作：案件台账、审批例外、待补材料、风险采纳、版本对比  
- 定制演示：CRM Mock 端口、泛微 OA Mock、多语言翻译与双语导出、同案附件、修订/原文/双语三模式导出  
- **不做** 16 条底限的 per-clause 向量 RAG（封闭规则集用确定性门控更稳）  
- 信审 **测算模型**（年报/评级自动授信）可独立演进；合同侧只消费「已生效」信审版本  
- 信审检索：受控词法候选召回 → 可选的百炼 Embedding 语义召回（RRF 融合）→ 必选 `qwen3-rerank` 精排 → ReAct 证据 Claim 核验

## 管理员系统设置

- 主审查模型、财报 ReAct 专用模型和合同脱敏模型
- 百炼 Embedding 与 `qwen3-rerank` 的地址、模型、密钥与财务数据传输授权
- 主模型 / Embedding / Rerank 连通性测试

配置以明文方式保存到 `backend/data/config.json`，系统设置页面仍只显示「已配置」。保存后重启后端生效。请确保该文件位于受限目录且不会提交到版本控制；`AUTH_SECRET` 和 `DATA_ENCRYPTION_KEY` 仍必须由部署环境或 `.env` 提供。

在百炼控制台开通并查看 embedding 模型后，以管理员身份进入「系统设置」：填写该页给出的模型 ID 与 API Key。经验证，当前百炼公有 Compatible API 地址为 `https://dashscope.aliyuncs.com/compatible-api/v1`（注意不是 `compatible-mode`）；Embedding 与 Rerank 分别使用其 `/embeddings`、`/reranks` 路径。勾选「启用 Embedding」及经合规批准的「授权发送财务证据」，将维度按模型文档填写（不需要指定时填 `0`）。保存、测试连接并重启后端。Embedding 只影响证据候选召回，不能单独产生事实、评分或授信审批结论。

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
