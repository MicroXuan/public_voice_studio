# 小宣 Voice Studio

一个面向公众的免费文本转语音工作台。后端使用 FastAPI 与 `edge-tts` 动态读取当前全部在线语音；前端是无框架静态页面，可部署到 Cloudflare Pages。

在线使用：[voiceflow.thexuan.com](https://voiceflow.thexuan.com)

## 能力

- 动态加载全部在线语音，支持搜索、语言/地区/性别筛选与本地收藏
- 单次文本最多 5,000 字符，每客户端每日最多生成 50,000 字符，可调语速、音调与音量
- 异步任务、生成进度、在线试听与 MP3 下载
- 每客户端小时/每日额度、同客户端单任务、全站 2 个并发与 8 个等待任务
- 不持久化用户文本；音频默认保留 1 小时
- 可选 Cloudflare Turnstile，人机验证未配置时自动关闭

## 本地开发

需要 Python 3.11+ 与 Node.js 20+。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/uvicorn backend.app.main:app --reload --port 8000
```

另开终端构建并预览前端：

```bash
API_BASE_URL=http://127.0.0.1:8000 npm run build
python3 -m http.server 5173 --directory dist
```

打开 `http://127.0.0.1:5173`。默认 CORS 已允许该本地地址。

## 测试

```bash
.venv/bin/python -m pytest -q
npm test
API_BASE_URL=http://127.0.0.1:8000 npm run build
```

## 部署

生产架构使用 Render Free 单 worker API 与 Cloudflare Pages 静态前端。免费实例冷启动时，页面会自动重试，不需要用户刷新。完整步骤、环境变量、自定义域名和回滚方式见 [部署文档](docs/deployment.md)。

- 正式网站：`https://voiceflow.thexuan.com`
- Pages 回源域名：`https://xiaoxuan-voice-studio.pages.dev`
- API：`https://xiaoxuan-voice-api.onrender.com`

## 重要说明

本项目依赖非官方的免费在线语音接口，适合首阶段免费、非关键业务使用，不承诺商业级 SLA。若未来加入付费或商业服务，应把 `SpeechSynthesizer` 接口替换为有正式授权与 SLA 的语音供应商，并迁移到持久化额度和任务存储。
