# 圣旨输入中……

你是架空大晟朝的新皇帝。自己写圣旨，在最多八个回合内决定王朝的走向。每回合三年，正常对局在第八回合以民心是否达到 80 判定胜负，严重危机可能提前结束对局。

[网页试玩（Qoder Sites）](https://shengzhi-gci8tb6txrw.qoder.zone)

- 阅读开局奏报，了解民心、国库和粮储，以及本局面临的困难。
- 写下一道政令，核对诏意预览，再确认颁布。
- 从人物反馈、国运事件和后续回响中判断是否调整施政。
- 终局可回看皇帝纪事、本朝评价和帝王图鉴。

大模型负责解释政令意图和生成叙事。资源变化、随机事件和胜负由规则引擎计算。前端使用 React、TypeScript 和 Vite，后端使用 FastAPI 和 SQLite。

## 本地运行

需要 Python 3.11+ 与 Node.js 18+。以下命令适用于 Windows PowerShell。

在第一个终端启动后端：

```powershell
cd backend
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

在另一个终端从仓库根目录启动前端：

```powershell
cd frontend
npm ci
npm run dev
```

打开 [本地游戏](http://localhost:5173)。默认使用固定演示模式，无需 API Key。如要接入真实模型，在后端的 `.env` 设置 `LLM_MODE=live`、`LLM_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`。开发时 Vite 会把 `/api` 请求代理到本地后端。独立部署前端时，可通过公开的 `VITE_API_BASE_URL` 设置 API 地址，并在后端通过 `CORS_ORIGINS` 放行前端来源。

## 检查

在 `backend` 使用对应 Python 环境运行 `python -m pytest`。在 `frontend` 运行 `npm run build` 检查类型和生产构建。

本项目使用 Qoder 辅助原型开发和网页发布，后续使用 Codex 辅助调试与迭代。
