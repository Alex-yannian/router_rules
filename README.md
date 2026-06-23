# router_rules

个人路由器（OpenWrt / OpenClash / mihomo 内核）分流规则聚合仓库。

GitHub Actions 每天自动从多个公开规则源下载、合并去重，生成 `dist/` 目录下
的成品规则文件。路由器只需订阅本仓库 `dist/` 里的文件，不需要同时连接
几十个上游站点。

## 重要说明：dist/ 产物的两类命名规则

由于 `.mrs` 是 mihomo 专属的二进制压缩格式，无法用脚本解析内容做跨源去重，
`dist/` 目录里有两类文件，对应两种不同的处理方式：

1. **`<分类>__<源名>.mrs`**（双下划线分隔）—— 来自官方/社区已经发布好的
   `.mrs` 格式源，原样镜像下载存储，**不做内容级去重**（直接订阅多个文件，
   mihomo 运行时依次匹配即可，不影响正确性，只有极小的重复匹配开销）。
   例如：`cn_domain__metacubex_cn_domain.mrs`、
   `apple_cn__666os_apple_cn.mrs`。

2. **`<分类>_manual.txt` / `<分类>_manual.mrs`** —— 来自纯文本/yaml格式源
   （如 AWAvenue 广告规则）解析出的域名，加上 `sources.yaml` 里手写的
   `extra_domains`，两者合并去重后输出。`.txt` 是明文，可以直接打开查看
   实际域名内容；`.mrs` 是用 mihomo 二进制正向转换出的二进制版（如果当时
   环境没有 mihomo 二进制，会只生成 `.txt`，路由器侧用
   `behavior: domain, format: text` 直接订阅 `.txt` 文件即可，功能完全等价）。

同一个分类如果既有镜像的 `.mrs` 又有 `_manual` 文件，路由器配置里把两者
都加进对应的 `rule-providers`，规则列表里都指向同一个目标策略组即可。

## 仓库结构

```
router_rules/
├── sources.yaml              # 规则源清单（唯一需要人工维护的文件）
├── scripts/
│   └── build.py              # 构建脚本：下载 -> （镜像 mrs / 解析文本）-> 输出
├── .github/workflows/
│   └── update.yml             # 每日定时任务 + 手动触发
└── dist/                      # 自动生成的成品规则
    ├── cn_domain__metacubex_cn_domain.mrs
    ├── ads__metacubex_ads.mrs
    ├── ads_manual.txt / ads_manual.mrs
    ├── ...
    └── _build_report.json     # 每次构建的成功/失败源记录
```

## 这个仓库本身**不包含**的内容

- 你的 Clash/mihomo 订阅链接
- `external-controller` 的 `secret`
- 任何其他个人敏感信息

这些信息只存在于你本地路由器上的配置文件里，不会出现在这个公开仓库的任何
文件中。本仓库的唯一职责是产出公开、可订阅的分流规则文件。

## 使用方法

1. 把这个文件夹 push 到你自己的 GitHub 仓库（公开仓库即可，因为内容本来就
   是公开规则的聚合）。
2. 进入仓库的 Settings -> Actions -> General，确认 Workflow permissions 设为
   "Read and write permissions"（否则 Action 无法把更新提交回仓库）。
3. 第一次可以去 Actions 标签页手动点 "Run workflow" 触发一次构建，确认能跑通。
4. 跑通后，`dist/` 目录下会出现各个分类的 `.txt` 和 `.mrs` 文件。把对应文件的
   raw 链接（形如 `https://raw.githubusercontent.com/<你的用户名>/router_rules/main/dist/cn_domain.mrs`）
   填入你路由器本地 yaml 的 `rule-providers` 对应位置即可。
5. 之后每天会自动重新构建、自动提交更新，你的路由器按 `interval` 设置的周期
   自动重新下载即可，无需手动干预。

## 风险声明（请自行判断）

`sources.yaml` 中标注了 `risk` 字段的源（主要是 666OS/rules 仓库的内容），
该上游仓库的 README 中声明"禁止转载发布到中国大陆境内的任何公共平台"。
本仓库使用 GitHub Actions 每日拉取其内容并存入本仓库的 `dist/` 目录，这一
行为是否落入该条款的限制范围，没有明确法律结论。使用者（也就是你）需要
自行判断并承担相应风险。如果你想完全规避这个不确定性，可以编辑
`sources.yaml`，删除所有标注了 `risk` 字段的条目，只保留 MetaCubeX 官方源，
重新触发一次构建即可生效。

## 容错说明

- 任何单个源下载失败，会跳过该源，使用其余源的内容继续合并，不会让整个
  分类的产出变成空文件。
- 如果某个分类的**所有**源都失败，该分类会保留上一次成功构建的旧文件，
  不会用空内容覆盖。
- 每次构建的详细成功/失败记录在 `dist/_build_report.json` 里，也会作为
  Action 的 Artifact 保留 14 天，方便排查。

## 维护

日常只需要编辑 `sources.yaml`：
- 想新增一个分类，在 `categories:` 下加一个新的键，写明 `fetch` 列表和/或
  `extra_domains` 手写补充域名。
- 想增删某个源，直接编辑对应分类下的 `fetch` 列表。
- 改完之后正常 push 到 main 分支即可，下一次定时任务会自动按新清单构建；
  也可以去 Actions 页面手动触发一次立即生效。
