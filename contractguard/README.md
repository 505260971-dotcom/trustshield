# ContractGuard · 合同评审协作中心

面向小团队的「信审前置、合同后置」协作工作台：信审人员先形成客户已生效的商业条件版本，业务人员提交合同必须绑定该版本；系统再完成合同底限审查及逐项信审越界校验，法务团队在案件台账中协作交付。

完整文档（命题、架构、API、演示）见仓库根目录 [`../docs/`](../docs/)。

## 默认本地管理员

演示账号见本机 `backend/.env` 中的 `INITIAL_ADMIN_*`（示例常为 `admin`）。正式环境请立即修改并使用密钥服务注入；`.env` 已被 Git 忽略。

## 启动

```powershell
.\dev.ps1
```

访问 `http://127.0.0.1:5173`。日志写入 `runtime/logs/`。

首次配置：

```powershell
copy backend\.env.example backend\.env
```

填写 `AUTH_SECRET`、`DATA_ENCRYPTION_KEY`、以及 `LLM_API_BASE` / `LLM_API_KEY` / `LLM_MODEL`。密码至少 10 位。生成加密密钥：

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## 信审与合同流程

```text
新建/更新客户信审条件（可经 CRM Mock 端口占位）-> 信审审批 -> 已生效版本
       -> 提交合同时强制绑定该版本（可附同案附件）
       -> 本地脱敏 -> 字段抽取 -> 底限词法规则候选
       -> 语义研判 -> 合同规则与信审条件确定性校验
       -> 信审越界：阻断，必须先更新信审并重新复审
       -> 合同法律风险：法务领取/改派、处置、OA Mock、翻译
       -> 导出 revised / plain / bilingual，或 Markdown / JSON
```

企业定制项对照：[`docs/01-产品与架构/enterprise-customization.md`](../docs/01-产品与架构/enterprise-customization.md)。

## 管理员系统设置

- 主审查模型的 OpenAI 兼容地址、模型名称和 API Key  
- 合同脱敏开关、本地智能脱敏模型  
- 主模型连接测试  

配置写入本机 `backend/.env`；密钥只显示「已配置」。保存后重启后端生效。规则候选使用词法门控，**无需 Embedding**。

## 目录

```text
contractguard/
├─ backend/
│  ├─ app/main.py                # API、案件流转、导出与翻译
│  ├─ app/graph/review_graph.py  # 合同评审 LangGraph
│  ├─ app/services/              # 解析、脱敏、规则、模型、导出
│  └─ data/                      # 本机 SQLite 与上传（不入库）
├─ frontend/src/                 # React + Ant Design
└─ runtime/                      # 启动日志（不入库）
```

## 验证

```powershell
cd backend
python scripts/test_security_workflow.py
python scripts/test_context_budget.py
python scripts/test_mask_fast_path.py
cd ..\frontend
npm run build
```
