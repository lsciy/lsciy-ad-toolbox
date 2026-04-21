# ============================================================
# summarizer.py — 归纳总结模块
# 本模块负责：
# 1. 按条件筛选计划数据（类目、类型、数值范围大于/小于）
# 2. 收集筛选出的计划中所有视频解析特征
# 3. 调用 Gemini 模型进行高阶归纳总结
# 4. 将总结结果以"时间+筛选条件"命名保存到项目根目录
# ============================================================

import os
import sys
from datetime import datetime

from data_manager import load_data


def filter_plans(data: dict, **criteria) -> dict:
    """
    根据传入的筛选条件过滤计划数据。

    筛选规则:
    - 字符串字段（category, type）：精确匹配
    - 数值字段：支持 min_xxx（大于等于）和 max_xxx（小于等于）
    - 若某字段在数据中为 null/None，则该计划视为不满足条件
    - 未传入的筛选条件不参与过滤

    支持的 criteria:
        category   (str):   产品类目精确匹配
        type       (str):   产品类型精确匹配
        min_cpm    (float): CPM 最小值（>=）
        max_cpm    (float): CPM 最大值（<=）
        min_ctr    (float): CTR 最小值
        max_ctr    (float): CTR 最大值
        min_cvr    (float): CVR 最小值
        max_cvr    (float): CVR 最大值
        min_roi    (float): ROI 最小值
        max_roi    (float): ROI 最大值
        min_ecpm   (float): eCPM 最小值
        max_ecpm   (float): eCPM 最大值

    返回:
        dict: 满足所有条件的计划子集（保留原始 plan_id 作为 Key）
    """
    # ---- 移除值为 None 的条件（即用户未传入该参数） ----
    active_criteria = {k: v for k, v in criteria.items() if v is not None}

    if not active_criteria:
        print("[信息] 未指定筛选条件，将使用全部计划数据。")
        return dict(data)

    print(f"[信息] 筛选条件: {active_criteria}")

    # ---- 数值字段到 JSON Key 的映射 ----
    numeric_field_map = {
        "cpm": "CPM", "ctr": "CTR", "cvr": "CVR",
        "roi": "ROI", "ecpm": "eCPM",
    }

    filtered = {}
    for plan_id, plan in data.items():
        match = True

        for crit_key, crit_val in active_criteria.items():
            # ---- 处理字符串类目匹配 ----
            if crit_key == "category":
                if plan.get("product_category") is None or plan["product_category"] != crit_val:
                    match = False
                    break

            elif crit_key == "type":
                if plan.get("product_type") is None or plan["product_type"] != crit_val:
                    match = False
                    break

            # ---- 处理数值范围筛选 ----
            elif crit_key.startswith("min_"):
                field_suffix = crit_key[4:]  # 去掉 "min_" 前缀
                json_key = numeric_field_map.get(field_suffix)
                if json_key:
                    val = plan.get(json_key)
                    # 字段为 None 时视为不满足条件
                    if val is None or val < crit_val:
                        match = False
                        break

            elif crit_key.startswith("max_"):
                field_suffix = crit_key[4:]  # 去掉 "max_" 前缀
                json_key = numeric_field_map.get(field_suffix)
                if json_key:
                    val = plan.get(json_key)
                    if val is None or val > crit_val:
                        match = False
                        break

        if match:
            filtered[plan_id] = plan

    print(f"[信息] 筛选结果: {len(filtered)} / {len(data)} 条计划满足条件。")
    return filtered


def collect_features(filtered_data: dict) -> str:
    """
    从筛选出的计划数据中提取所有视频解析特征，拼接为单一字符串。
    不包含视频文件名，仅拼接特征文本内容。

    返回:
        str: 用分隔线连接的所有特征文本；无特征时返回空字符串
    """
    features = []
    for plan_id, plan in filtered_data.items():
        summarization = plan.get("summarization", {})
        for _filename, feature_text in summarization.items():
            if feature_text and feature_text.strip():
                features.append(feature_text.strip())

    if not features:
        print("[警告] 筛选出的计划中没有已解析的视频特征数据。")
        print("       请先使用 parse 命令对相关计划的视频进行解析。")
        return ""

    print(f"[信息] 共收集到 {len(features)} 条视频特征解析结果。")

    # ---- 用分隔线连接各条特征 ----
    return "\n\n---\n\n".join(features)


def run_summarize(client, features_text: str, config: dict) -> str:
    """
    调用 Gemini 模型对收集到的特征进行高阶归纳总结。

    返回:
        str: 模型生成的总结文本
    """
    from google.genai import types

    model_name = config.get("models", {}).get("summarize_model", "gemini-3.1-pro-preview")
    sys_instr = config.get("prompts", {}).get("summarize", {}).get("system_instruction", "")
    user_instr_template = config.get("prompts", {}).get("summarize", {}).get("user_instruction", "{features}")
    temperature = config.get("generation", {}).get("summarize_temperature", 0.7)
    max_tokens = config.get("generation", {}).get("summarize_max_output_tokens", 65536)

    # ---- 将特征文本填入用户指令模板的 {features} 占位符 ----
    user_prompt = user_instr_template.replace("{features}", features_text)

    gen_config = types.GenerateContentConfig(
        system_instruction=sys_instr.strip(),
        temperature=temperature,
        max_output_tokens=max_tokens,
    )

    print(f"[信息] 正在调用 {model_name} 进行归纳总结...")
    response = client.models.generate_content(
        model=model_name,
        config=gen_config,
        contents=[user_prompt],
    )

    return response.text if response.text else ""


def build_filename(criteria: dict) -> str:
    """
    根据当前时间和筛选条件生成输出文件名。
    格式: summary_YYYYMMDD_HHMMSS_条件描述.md
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ---- 构造条件描述 ----
    parts = []
    label_map = {
        "category": "类目", "type": "类型",
        "min_cpm": "CPM≥", "max_cpm": "CPM≤",
        "min_ctr": "CTR≥", "max_ctr": "CTR≤",
        "min_cvr": "CVR≥", "max_cvr": "CVR≤",
        "min_roi": "ROI≥", "max_roi": "ROI≤",
        "min_ecpm": "eCPM≥", "max_ecpm": "eCPM≤",
    }
    for key, val in criteria.items():
        if val is not None:
            label = label_map.get(key, key)
            if key in ("category", "type"):
                parts.append(f"{label}={val}")
            else:
                parts.append(f"{label}{val}")

    condition_str = "_".join(parts) if parts else "全量"

    # ---- 清理文件名中不安全的字符 ----
    safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_=≥≤."
                     "一二三四五六七八九十百千万亿"
                     "类目型全量美妆口红护肤彩妆食品饮料服装数码家居教育游戏金融")
    # 对于中文和常见字符直接保留，其他特殊字符替换为下划线
    cleaned = ""
    for ch in condition_str:
        if ch.isalnum() or ch in "_=≥≤." or '\u4e00' <= ch <= '\u9fff':
            cleaned += ch
        else:
            cleaned += "_"

    return f"summary_{timestamp}_{cleaned}.md"


def save_summary(result: str, criteria: dict) -> str:
    """
    将总结结果保存为 Markdown 文件到项目根目录。
    文件名格式: summary_时间戳_筛选条件.md

    返回:
        str: 保存的文件路径
    """
    filename = build_filename(criteria)
    filepath = os.path.join(".", filename)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            # ---- 写入文件头（包含筛选条件元信息） ----
            f.write(f"# 广告素材归纳总结报告\n\n")
            f.write(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

            active = {k: v for k, v in criteria.items() if v is not None}
            if active:
                f.write(f"> 筛选条件: {active}\n")
            else:
                f.write(f"> 筛选条件: 全量数据\n")

            f.write(f"\n---\n\n")
            f.write(result)

        print(f"[信息] 总结报告已保存: {filepath}")
        return filepath

    except Exception as e:
        print(f"[错误] 保存总结报告失败: {e}")
        # 兜底: 直接打印到控制台
        print("\n===== 总结结果（控制台输出） =====\n")
        print(result)
        return ""


def summarize_command(config: dict, data: dict, **criteria) -> None:
    """
    归纳总结命令的主入口函数。

    流程: 筛选数据 → 收集特征 → 调用模型 → 保存结果
    """
    # ---- 步骤 1: 按条件筛选计划 ----
    filtered = filter_plans(data, **criteria)

    if not filtered:
        print("[提示] 未筛选到任何符合条件的计划，程序终止。")
        print("       请检查筛选条件或确认数据是否已录入。")
        return

    # ---- 步骤 2: 收集所有特征文本 ----
    features_text = collect_features(filtered)

    if not features_text:
        print("[提示] 筛选出的计划中没有可用的解析结果，程序终止。")
        return

    # ---- 步骤 3: 创建客户端并调用模型 ----
    from config_loader import get_client
    client = get_client(config)

    try:
        result = run_summarize(client, features_text, config)
    except Exception as e:
        print(f"[错误] 调用总结模型时发生异常: {type(e).__name__}: {e}")
        return

    if not result.strip():
        print("[警告] 模型返回了空的总结结果。")
        return

    # ---- 步骤 4: 保存结果 ----
    save_summary(result, criteria)
