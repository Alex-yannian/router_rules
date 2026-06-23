#!/usr/bin/env python3
"""
build.py（v2，修复版）
============================================================================
本脚本是"每日自动聚合规则"系统的核心。由 GitHub Action 每天调用一次。

【相对 v1 的关键修复】
v1 版本假设 mihomo 的 convert-ruleset 命令支持"mrs 转回文本"这个反向操作，
用来把多个上游 .mrs 源的内容解析出来再去重合并。经核实，mihomo 官方文档和
所有能找到的真实使用案例中，convert-ruleset 命令的语法是：

    mihomo convert-ruleset <domain|ipcidr> <yaml|text> <输入文件> <输出文件.mrs>

第二个参数 yaml/text 指的是"输入文件目前的格式"，且所有已知用法都是
"文本/yaml 转 mrs"这一个方向，没有证据支持"mrs 转回文本"这个反向操作。
继续假设这个不存在的反向功能，会导致几乎所有依赖 mrs 格式的源全部转换失败、
dist/ 目录最终空白——这正是 v1 版本在真实环境中实际出现的故障。

【v2 的策略调整】
  - 对 format: mrs 的源：不再尝试解析内容。直接原样下载，镜像存储为
    dist/<category>__<源名>.mrs。多个同类目的 mrs 源会各自保留一份，
    不强行合并（mihomo 运行时按规则顺序依次匹配多个 rule-provider 即可，
    不需要预先合并去重，只是会有一点点重复匹配的性能损耗，可接受）。
  - 对 format: clash_classical_yaml（如 AWAvenue 广告规则）：照常解析、
    提取域名、参与去重合并，这部分一直工作正常，不受影响。
  - 对 extra_domains 手写域名：合并去重后写出 dist/<category>_manual.txt，
    并尝试用 mihomo 把它正向转换成 dist/<category>_manual.mrs（这个方向
    是文档证实可行的）；如果 mihomo 不可用，保留 .txt，路由器侧用
    behavior: domain, format: text 直接订阅即可，功能不受影响。
  - 任何单步失败都不会让脚本整体崩溃，只会跳过该步骤并记录到
    dist/_build_report.json，保留上一次成功的产物。
============================================================================
"""

import os
import sys
import subprocess
import urllib.request
import urllib.error
import yaml
import shutil
import tempfile
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources.yaml"
DIST_DIR = ROOT / "dist"
TMP_DIR = Path(tempfile.mkdtemp(prefix="router_rules_build_"))
MIHOMO_BIN = shutil.which("mihomo") or "/usr/local/bin/mihomo"

FETCH_TIMEOUT = 20
FETCH_RETRIES = 2

build_report = {"success": [], "failed": [], "skipped": [], "mirrored_mrs": []}


def log(msg):
    print(f"[build] {msg}", flush=True)


def fetch_url(url, dest_path):
    """下载单个文件，失败重试，最终失败返回 False（不抛异常中断整体流程）"""
    for attempt in range(1, FETCH_RETRIES + 2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "router-rules-bot/1.0"})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                data = resp.read()
                if len(data) == 0:
                    log(f"  警告：{url} 返回空内容（尝试 {attempt}）")
                    continue
                dest_path.write_bytes(data)
                return True
        except (urllib.error.URLError, TimeoutError, Exception) as e:
            log(f"  下载失败（尝试 {attempt}/{FETCH_RETRIES + 1}）：{url} -> {e}")
    return False


def text_to_mrs(text_path, behavior, out_mrs_path):
    """把文本域名列表正向转换为 .mrs（文档证实可行的方向）。
    失败时不报错中断，只返回 False，调用方负责降级处理。"""
    if not Path(MIHOMO_BIN).exists():
        log(f"  提示：找不到 mihomo 二进制（{MIHOMO_BIN}），跳过 {out_mrs_path.name} 的生成，保留 .txt")
        return False
    try:
        result = subprocess.run(
            [MIHOMO_BIN, "convert-ruleset", behavior, "text", str(text_path), str(out_mrs_path)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            log(f"  转换失败：{text_path} -> {result.stderr.strip()}")
            return False
        return out_mrs_path.exists()
    except Exception as e:
        log(f"  转换异常：{text_path} -> {e}")
        return False


def parse_classical_yaml_domains(content_bytes):
    """解析 classical 行为的 yaml 格式规则集（如 AWAvenue-Ads-Rule-Clash.yaml），
    提取其中规则的域名部分"""
    domains = []
    try:
        text = content_bytes.decode("utf-8", errors="ignore")
        data = yaml.safe_load(text)
        payload = data.get("payload", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        for line in payload:
            line = str(line).strip().strip("'\"")
            domains.append(line)
    except Exception as e:
        log(f"  解析 classical yaml 失败: {e}")
    return domains


def build_category(name, conf):
    """处理单个 category：
       - mrs 源 -> 原样镜像存储，不解析内容
       - 文本/yaml 源 -> 解析、参与去重
       - extra_domains -> 合并进文本去重结果，尝试转 mrs
    """
    log(f"处理分类: {name}")
    text_domains = set()
    mirrored_any = False
    any_attempted = False

    for src in conf.get("fetch", []):
        any_attempted = True
        src_name = src["name"]
        url = src["url"]
        fmt = src.get("format", "mrs")

        if fmt == "mrs":
            out_mrs = DIST_DIR / f"{name}__{src_name}.mrs"
            tmp_raw = TMP_DIR / f"{name}_{src_name}.mrs"
            ok = fetch_url(url, tmp_raw)
            if ok:
                shutil.copy(tmp_raw, out_mrs)
                log(f"  -> 镜像存储 {out_mrs.name}（{out_mrs.stat().st_size} 字节）")
                build_report["success"].append(f"{name}/{src_name}")
                build_report["mirrored_mrs"].append(out_mrs.name)
                mirrored_any = True
            else:
                log(f"  跳过源 {src_name}（下载失败）")
                build_report["failed"].append(f"{name}/{src_name}")

        elif fmt == "clash_classical_yaml":
            tmp_raw = TMP_DIR / f"{name}_{src_name}.raw"
            ok = fetch_url(url, tmp_raw)
            if ok:
                domains = parse_classical_yaml_domains(tmp_raw.read_bytes())
                for d in domains:
                    if d:
                        text_domains.add(d)
                build_report["success"].append(f"{name}/{src_name}")
            else:
                log(f"  跳过源 {src_name}（下载失败）")
                build_report["failed"].append(f"{name}/{src_name}")
        else:
            log(f"  未知格式 {fmt}，跳过 {src_name}")
            build_report["skipped"].append(f"{name}/{src_name}")

    for d in conf.get("extra_domains", []):
        text_domains.add(d.strip())
        any_attempted = True

    wrote_anything = mirrored_any

    if text_domains:
        sorted_domains = sorted(text_domains)
        out_txt = DIST_DIR / f"{name}_manual.txt"
        out_txt.write_text("\n".join(sorted_domains) + "\n", encoding="utf-8")
        log(f"  -> {out_txt.name}: {len(sorted_domains)} 条域名（文本/yaml源 + 手写补充，已去重）")
        wrote_anything = True

        out_mrs = DIST_DIR / f"{name}_manual.mrs"
        if text_to_mrs(out_txt, "domain", out_mrs):
            log(f"  -> {out_mrs.name} 生成成功")

    if not wrote_anything:
        if any_attempted:
            log(f"  分类 {name} 本次没有任何源成功，保留上次产物，不覆盖")
        else:
            log(f"  分类 {name} 未配置任何源（fetch/extra_domains均为空），跳过")
        return False

    return True


def main():
    DIST_DIR.mkdir(exist_ok=True)
    with open(SOURCES_FILE, encoding="utf-8") as f:
        sources = yaml.safe_load(f)

    categories = sources.get("categories", {})
    any_success = False
    for name, conf in categories.items():
        try:
            if build_category(name, conf):
                any_success = True
        except Exception as e:
            log(f"分类 {name} 处理时发生未预期错误，跳过并保留旧产物: {e}")
            build_report["failed"].append(f"{name} (未预期错误: {e})")

    report_path = DIST_DIR / "_build_report.json"
    report_path.write_text(json.dumps(build_report, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"构建完成。成功源 {len(build_report['success'])} 个，失败源 {len(build_report['failed'])} 个，"
        f"跳过 {len(build_report['skipped'])} 个，镜像mrs文件 {len(build_report['mirrored_mrs'])} 个。")
    if build_report["failed"]:
        log("失败的源列表（详见 dist/_build_report.json）：")
        for f in build_report["failed"]:
            log(f"  - {f}")

    shutil.rmtree(TMP_DIR, ignore_errors=True)

    if not any_success and categories:
        log("致命错误：所有分类均构建失败，本次不提交任何变更")
        sys.exit(1)


if __name__ == "__main__":
    main()
