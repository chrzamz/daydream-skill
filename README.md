# 白日梦 · Daydream

**从日常碎片里发现可能，把想法简短说清楚。**

An agent skill for bold, cross-domain idea discovery, grounded in personal context and lightweight public research. Responds in your language. Works with Codex, Claude Code, and other agents that support Agent Skills.

Daydream 从聊天、笔记、提醒、日常观察与外部讨论中寻找连接，提出可供选择的新想法。方向可以是内容、个人 IP、消费产品、工具、服务、业务项目，也可以超出这些分类。

它不会默认把讨论变成长篇访谈或体验剧本。默认输出是：**想法标题 + 一两句描述 + 查到的有用线索**。你选中后，再按需要深入。

## 安装

需要 Node.js **22.20+**。通过 Vercel 的开源 `skills` CLI 安装：

```sh
npx skills add chrzamz/daydream-skill --skill daydream
```

全局安装到 Codex 和 Claude Code：

```sh
npx skills add chrzamz/daydream-skill --skill daydream -g -a codex -a claude-code
```

查看仓库中的 Skill、列出已安装技能，或更新已安装版本：

```sh
npx skills add chrzamz/daydream-skill --list
npx skills list -g
npx skills update daydream -g
```

也可以把 [`skills/daydream`](skills/daydream) 整个目录放进宿主支持的技能目录。启动新会话或按宿主方式刷新技能后使用。

## 怎么用

```text
用 $daydream 从最近的聊天和笔记里找几个新想法，范围大胆一点，每个简单描述。

用白日梦看看这个念头能长成什么，并去 Hacker News、Product Hunt 找一点外部信号。

从这份材料里挖三个有辨识度的小红书或公众号选题，给出标题和切入角度。

第二个想法有意思。帮我查真实使用场景，再改成一个可以小范围验证的版本。
```

Claude Code 可使用 `/daydream`，Codex 可使用 `$daydream`；也可按描述自然触发。

## 它如何工作

1. 从已有材料或公开信号出发，区分用户想法、AI 建议、已有项目和后续决定。
2. 跨领域联想，尝试新受众、新场景、新形式和意外组合。
3. 在萌发期做适量公开检索：真实抱怨、临时解决办法、现有产品、不同意见。
4. 简短提出候选。竞品存在不直接否决；点赞不等于付费；没有结果就保留为未知。
5. 你选中以后再深入。保留已取消、已完成和明确暂缓的决定。

个人记录是起点之一，不是想象力的边界。只出现过一次的念头也值得探索。输出风格见 [示例](skills/daydream/references/examples.md)。

## 数据来源与边界

核心 Skill 不要求 Python 或特定账号：可以直接处理当前聊天、你提供的材料，以及宿主已有的搜索能力。

附带的可选工具使用 Python **3.9+ 标准库**：

- `collect_signals.py`：读取明确指定的 Claude Code、Codex JSONL、Markdown 和通用 JSON/JSONL 导出。
- `collect_apple.py`：macOS 上通过应用接口只读采集指定 Notes 文件夹或 Reminders 列表；需要系统已有授权。

两个采集工具均不调用网络、不修改源内容。它们会跳过常见凭据记录，但**不保证完整识别所有隐私信息**；应选择合适的文件夹和列表。宿主模型是否在本地运行，取决于你使用的 Agent，不能因采集脚本在本地就宣称整个处理过程完全离线。

OpenCode、Gemini 或其他来源可使用宿主连接器或通用导出；本版没有内置它们的私有数据库解析器。详见 [来源说明与命令](skills/daydream/references/sources.md)。

Hacker News、Product Hunt 和社媒检索使用宿主可用的连接器、CLI 或网页搜索；本 Skill 不承诺平台访问权限，也不会绕过登录或权限限制。

安装不会启动常驻进程或定时任务。需要定期运行时，可在支持调度的宿主里明确设置，按增量读取并只通知有意义的新发现。

## 发布到 skills.sh

Skill 文件托管在 GitHub。根据 [skills.sh 官方 FAQ](https://skills.sh/docs/faq)，用户通过 `npx skills add owner/repo` 正常安装后，平台会通过匿名安装遥测自动发现和统计；无需部署 Vercel 网站，也没有额外的 Skill 包上传步骤。

公开仓库可安装，不代表榜单立刻可搜索或已经通过平台审核。收录与审核可能存在延迟。不要为了排名反复制造安装记录。

## 开发与验证

```sh
python3 -B -m unittest discover -s tests -v
```

测试使用合成数据，覆盖采集、噪音排除、去重、时间筛选和凭据跳过等行为。技能行为场景在 [evals/scenarios.md](evals/scenarios.md)；自动测试不证明创意质量或市场需求。

仓库不包含用户的真实对话、备忘录、客户信息或个人路径。私人工作数据应存到本仓库以外。

## License

[MIT](LICENSE)
