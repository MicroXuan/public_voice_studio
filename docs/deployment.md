# 小宣 Voice Studio 部署与运维

## 当前生产环境

- 正式网站：`https://voiceflow.thexuan.com`
- Cloudflare Pages：`https://xiaoxuan-voice-studio.pages.dev`
- Render API：`https://xiaoxuan-voice-api.onrender.com`
- 健康检查：`https://xiaoxuan-voice-api.onrender.com/healthz`

## 架构

- 前端：Cloudflare Pages，构建后只包含 `index.html`、CSS、浏览器 JavaScript 和公开配置。
- API：Render Free Docker Web Service，FastAPI + Uvicorn 单 worker。
- 数据：内存任务与额度状态；临时 MP3 写入 `/tmp/xiaoxuan-voice-audio`，默认 1 小时清理。

选择单 worker 是为了让队列、额度和任务状态保持一致。Render 重启或休眠后，内存额度会重置，旧任务也会消失；前端会保留用户输入并提示重新提交。

## 1. 部署 Render Free API

1. 将仓库推送到 GitHub `main`。
2. 登录 Render，选择 **New > Blueprint**，连接 `MicroXuan/public_voice_studio`。
3. Render 会读取根目录的 `render.yaml`，创建 `xiaoxuan-voice-api` 免费 Web Service。
4. 首次创建时填写 `ALLOWED_ORIGINS`。尚未创建 Pages 时，可先填预期域名与本地开发地址，例如：

   ```text
   https://xiaoxuan-voice-studio.pages.dev,https://voiceflow.thexuan.com,http://localhost:5173,http://127.0.0.1:5173
   ```

5. `IP_HASH_SECRET` 由 Render 自动生成。`TURNSTILE_SECRET_KEY` 可留空；需要防滥用时再填写。
6. 部署完成后记录 `https://xiaoxuan-voice-api.onrender.com` 一类的服务 URL，并访问 `/healthz` 验证。

Render Free 闲置后会休眠，冷启动可能接近 1 分钟。前端会自动重试语音目录和保留用户文本，无需刷新网页。运行目录是临时文件系统，不要把它当永久存储。

### Render 环境变量

| 名称 | 必需 | 说明 |
| --- | --- | --- |
| `ALLOWED_ORIGINS` | 是 | 逗号分隔的正式前端 Origin 与本地开发 Origin；兼容旧名 `CORS_ORIGINS` |
| `IP_HASH_SECRET` | 是 | HMAC 匿名客户端标识；兼容旧名 `CLIENT_IDENTITY_SECRET` |
| `OUTPUT_DIR` | 是 | `/tmp/xiaoxuan-voice-audio` |
| `TURNSTILE_SECRET_KEY` | 否 | Cloudflare Turnstile 私钥，只放在 Render |
| `FORWARDED_ALLOW_IPS` | 是 | Render 容器只由平台入口代理访问，使用 `*` 让 Uvicorn采用平台处理后的客户端地址 |

不要在日志中输出请求正文、原始 IP 或环境变量。

## 2. 部署 Cloudflare Pages

1. 在 Cloudflare 控制台进入 **Workers & Pages > Create > Pages > Import an existing Git repository**。
2. 选择 `MicroXuan/public_voice_studio`，生产分支选 `main`。
3. 使用以下构建设置：

   | 设置 | 值 |
   | --- | --- |
   | Framework preset | None |
   | Build command | `npm run build` |
   | Build output directory | `dist` |
   | Root directory | 仓库根目录 |

4. 在 Pages 的生产环境变量中添加：
   - `API_BASE_URL`：`https://xiaoxuan-voice-api.onrender.com`，不带末尾 `/`。
   - `NODE_VERSION`：`22`。
   - `TURNSTILE_SITE_KEY`：可选的公开站点密钥；未启用时留空。
5. 部署成功后得到 `*.pages.dev` 地址。回到 Render，把该 Origin 加进 `ALLOWED_ORIGINS` 并重新部署。

构建脚本只把公开资源复制到 `dist`，并只注入 API URL 与公开的 Turnstile site key。任何私钥都不会进入前端产物。

### 访问统计

在 Pages 项目进入 **Metrics > Web Analytics > Enable**。Cloudflare 会在下一次部署时自动注入统计脚本，无需在仓库中保存站点令牌；访问量、访客数和页面性能只在 Cloudflare 控制台中查看，不在公开页面显示。

## 3. 绑定自定义域名

### 前端主域名

在 Pages 项目进入 **Custom domains > Set up a domain**，添加 `voiceflow.thexuan.com`。如果域名已托管在同一 Cloudflare 账户，DNS 记录会自动引导完成；否则按界面提供的 CNAME 记录配置。

绑定后：

1. 把 `https://voiceflow.thexuan.com` 加到 Render 的 `ALLOWED_ORIGINS`。
2. 保留 `*.pages.dev` Origin 直到自定义域名验证完成；确认稳定后可移除。
3. 重新测试 OPTIONS、语音目录、生成、轮询、试听和下载。

### 可选 API 子域名

首阶段可以直接使用 Render URL，最省配置。若要使用 `api.voice.example.com`，在 Render 服务 **Settings > Custom Domains** 添加它，再把 Pages 的 `API_BASE_URL` 改为该地址并重新构建。

## 4. Turnstile（可选）

在 Cloudflare Turnstile 创建站点：

1. 把 site key 配置为 Pages 的 `TURNSTILE_SITE_KEY`。
2. 把 secret key 配置为 Render 的 `TURNSTILE_SECRET_KEY`。
3. 两端都重新部署，验证生成前出现人机验证且失败时返回 403。

site key 是公开配置，secret key 只能存在 Render。

## 5. 验证清单

```bash
.venv/bin/python -m pytest -q
npm test
API_BASE_URL=http://127.0.0.1:8000 npm run build
docker build -t xuan-voice-studio:local .
docker run --rm -p 8000:8000 xuan-voice-studio:local
```

生产检查：

- `/healthz` 返回 200，且不会触发语音目录请求。
- 正式域名允许 CORS；未知 Origin 没有允许头。
- 所有语音可搜索，长名称不撑破布局，空结果有提示。
- 生成中刷新轮询不会重复提交；服务重启后提示重新提交，文本仍保留。
- 下载响应为 MP3；约 1 小时后文件不可用。
- 375、768、1024、1440px 均无横向滚动或内容遮挡。

## 6. 监控、回滚与迁移

Render 的 `/healthz` 用作部署健康检查。若新版本检查失败，Render 不会把流量切到失败实例。日常排障先看健康状态、队列错误率和上游连接错误，不记录文本内容。

回滚时，在 Render 的 Deploys 选择上一个成功版本重新部署；Cloudflare Pages 在 Deployments 选择上一个生产部署执行回滚。回滚后再次检查 CORS 环境变量是否与前端域名一致。

未来商业化时应迁移：

1. 将临时内存额度迁移到 Redis 或数据库。
2. 将任务与音频迁移到持久队列和对象存储。
3. 在不改 API/前端的前提下替换 `SpeechSynthesizer` 实现，选择具备正式许可、配额、监控和 SLA 的服务。
4. 增加账户、计费、审计与删除策略后再开放商业套餐。
