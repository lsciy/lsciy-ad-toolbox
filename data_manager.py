# ============================================================
# data_manager.py — 数据存储与管理模块
# 本模块负责：
# 1. 从 data.json 读取全量数据（以 plan_id 为主键的字典）
# 2. 原子化写入 data.json（防止写入中断导致数据损坏）
# 3. 计算 eCPM 指标
# 4. 插入或更新计划记录（upsert 逻辑）
# ============================================================

import json
import os
import tempfile

# ---- 默认数据文件路径 ----
DEFAULT_DATA_PATH = "data.json"


def load_data(data_path: str = DEFAULT_DATA_PATH) -> dict:
    """
    从 JSON 文件中读取全量广告计划数据。

    参数:
        data_path: 数据文件路径，默认为 data.json

    返回:
        dict: 以 plan_id 为 Key 的数据字典；文件不存在时返回空字典

    异常处理:
        - 文件不存在：返回空字典（视为首次运行）
        - JSON 格式错误：打印错误信息并返回空字典
        - 读取权限错误：打印提示并返回空字典
    """
    # ---- 文件不存在时返回空字典，视为首次使用 ----
    if not os.path.isfile(data_path):
        print(f"[信息] 数据文件 {data_path} 不存在，将创建新文件。")
        return {}

    try:
        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # ---- 确保读取到的是字典类型 ----
        if not isinstance(data, dict):
            print(f"[警告] 数据文件格式异常（期望字典，实际为 {type(data).__name__}），将重置为空数据。")
            return {}

        print(f"[信息] 已加载 {len(data)} 条计划数据。")
        return data

    except json.JSONDecodeError as e:
        print(f"[错误] 数据文件 JSON 格式错误: {e}")
        print("       请检查 data.json 文件内容是否为有效的 JSON 格式。")
        return {}

    except PermissionError:
        print(f"[错误] 没有权限读取数据文件: {data_path}")
        return {}

    except Exception as e:
        print(f"[错误] 读取数据文件时发生未知错误: {e}")
        return {}


def save_data(data: dict, data_path: str = DEFAULT_DATA_PATH) -> bool:
    """
    将数据字典原子化地写入 JSON 文件。

    原子化写入策略：
    1. 先将数据写入同目录下的临时文件
    2. 写入成功后，使用 os.replace() 原子性地替换目标文件
    3. 这样即使写入过程中程序崩溃，原文件也不会损坏

    参数:
        data:      要保存的数据字典
        data_path: 目标文件路径

    返回:
        bool: 保存成功返回 True，失败返回 False
    """
    try:
        # ---- 获取目标文件所在目录，用于创建临时文件 ----
        target_dir = os.path.dirname(os.path.abspath(data_path))

        # ---- 在同目录下创建临时文件（确保在同一文件系统上，os.replace 才能原子化） ----
        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix="data_",
            dir=target_dir
        )

        try:
            # ---- 写入 JSON 数据到临时文件 ----
            # ensure_ascii=False: 保持中文可读性
            # indent=2: 格式化输出，方便人工查看
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # ---- 原子性替换目标文件 ----
            os.replace(tmp_path, data_path)
            return True

        except Exception:
            # ---- 写入失败时清理临时文件 ----
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    except PermissionError:
        print(f"[错误] 没有权限写入数据文件: {data_path}")
        return False

    except Exception as e:
        print(f"[错误] 保存数据文件时发生错误: {e}")
        return False


def calculate_ecpm(cpm: float | None, ctr: float | None, cvr: float | None) -> float | None:
    """
    计算 eCPM（有效千次展示成本 / 千次展示价值）。

    计算公式: eCPM = CPM × CTR × CVR × 1000

    参数:
        cpm: 千次展示成本（Cost Per Mille），可为 None
        ctr: 点击率（Click Through Rate），可为 None
        cvr: 转化率（Conversion Rate），可为 None

    返回:
        float | None: 计算得到的 eCPM 值；任一输入为 None 时返回 None

    示例:
        calculate_ecpm(20.5, 0.05, 0.02)  → 20.5
        calculate_ecpm(20.5, None, 0.02)  → None
    """
    # ---- 任一字段缺失时无法计算，返回 None ----
    if cpm is None or ctr is None or cvr is None:
        return None

    return cpm * ctr * cvr * 1000


def upsert_plan(data: dict, plan_id: str, **kwargs) -> dict:
    """
    插入新计划或更新已有计划的记录。

    如果 plan_id 已存在，则仅更新传入的非 None 字段；
    如果 plan_id 不存在，则创建包含所有字段的新记录。

    支持的 kwargs 参数:
        product_category (str):  产品类目（如"美妆"）
        product_type     (str):  产品类型（如"口红"）
        CPM              (float): 千次展示成本
        CTR              (float): 点击率
        CVR              (float): 转化率
        ROI              (float): 投资回报率

    参数:
        data:    当前全量数据字典
        plan_id: 计划 ID（字符串）
        **kwargs: 要更新的字段键值对

    返回:
        dict: 更新后的完整计划记录
    """
    # ---- 允许更新的字段白名单 ----
    allowed_fields = {
        "product_category", "product_type",
        "CPM", "CTR", "CVR", "ROI"
    }

    # ---- 获取已有记录，若不存在则创建默认结构 ----
    if plan_id in data:
        plan = data[plan_id]
        is_update = True
    else:
        # 新建计划时初始化所有字段为 None
        plan = {
            "product_category": None,
            "product_type": None,
            "CPM": None,
            "CTR": None,
            "CVR": None,
            "ROI": None,
            "eCPM": None,
            "summarization": {}  # 视频解析结果字典，Key=视频文件名, Value=特征字符串
        }
        is_update = False

    # ---- 更新传入的字段 ----
    updated_fields = []
    for key, value in kwargs.items():
        if key in allowed_fields:
            # 只有当值不是 None 或者是新建记录时才更新
            # 这样可以避免已有值被意外覆盖为 None
            if value is not None or not is_update:
                plan[key] = value
                if value is not None:
                    updated_fields.append(f"{key}={value}")

    # ---- 自动计算 eCPM ----
    plan["eCPM"] = calculate_ecpm(plan.get("CPM"), plan.get("CTR"), plan.get("CVR"))

    # ---- 确保 summarization 字段存在 ----
    if "summarization" not in plan:
        plan["summarization"] = {}

    # ---- 将记录写回数据字典 ----
    data[plan_id] = plan

    # ---- 打印操作日志 ----
    action = "更新" if is_update else "新建"
    print(f"[信息] 已{action}计划 [{plan_id}]")
    if updated_fields:
        print(f"       更新字段: {', '.join(updated_fields)}")
    if plan["eCPM"] is not None:
        print(f"       eCPM 计算结果: {plan['eCPM']:.4f}")
    else:
        print("       eCPM: 无法计算（CPM/CTR/CVR 存在空值）")

    return plan
