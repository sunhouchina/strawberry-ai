# 草莓智农助手（MVP）

面向设施草莓种植的**保守型生产辅助系统**：拍照/文字观察记录与风险初筛、中文农事描述到结构化台账草稿，以及农技员审核与审计留痕。

> 本项目不调用外部 LLM、图像模型、天气 API 或农药数据库。风险判断由可审计的确定性规则完成，并为未来 RAG/LLM 提供服务边界。

## 安全边界

- 不提供农药剂量、稀释浓度、混配方案或采收安全间隔；相关请求会被拦截并升级给农技员。
- 图片或上下文不足时，系统会明确表达不确定性，并要求补拍或补充棚室、生育期和近期管理信息。
- 初筛结果不是最终诊断；中高风险记录必须由农技员确认。

详见 `docs/strawberry-mvp.md` 与 `docs/knowledge-base-and-risk-rules.md`。

## 快速开始

```bash
cp .env.example .env
docker compose up --build
```

API 默认运行在 `http://localhost:8000`，接口文档在 `/docs`。

本地开发（Python 3.12+）：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
pytest
```

或从仓库根目录运行：`make test`、`make lint`、`make migrate`。

## MVP 工作流

1. 创建农场、棚室和草莓种植批次；
2. 通过 `POST /api/v1/observations` 提交图片引用与症状描述；
3. 确定性规则返回候选类别、风险等级、补充问题和人工审核建议；
4. 农技员审核中高风险问题；
5. 通过 `POST /api/v1/farming-records/draft` 生成中文农事描述的可编辑台账草稿，并确认保存。

## 已知限制

- 图片仅作为 URL/对象存储引用保存，不做图像识别；
- 中文台账解析只覆盖 MVP 的常见表达；
- 当前无认证与 RBAC，生产部署前必须补齐身份、权限、签名上传、备份和审计策略。
