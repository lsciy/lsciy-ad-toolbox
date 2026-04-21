# ============================================================
# video_parser.py — 短视频广告素材解析模块
# 本模块负责：
# 1. 扫描指定计划目录下的视频文件
# 2. 通过 Google GenAI File API 上传视频并等待处理完成
# 3. 调用 Gemini 模型对视频进行特征要素解析
# 4. 实现断点续传（已解析的视频自动跳过）
# 5. 每解析一个视频立即保存结果，防止数据丢失
# ============================================================

import os
import time
import mimetypes

from data_manager import load_data, save_data

# 支持的视频文件扩展名
SUPPORTED_VIDEO_EXTENSIONS = {
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
    ".flv", ".wmv", ".mpeg", ".mpg", ".3gp"
}


def get_video_files(plan_id: str, materials_dir: str = "materials") -> list[str]:
    """
    扫描 ./materials/{plan_id}/ 目录下的所有视频文件。
    返回视频文件的绝对路径列表（按文件名排序）。
    目录不存在或无视频文件时返回空列表。
    """
    plan_dir = os.path.join(materials_dir, str(plan_id))

    if not os.path.isdir(plan_dir):
        print(f"[错误] 素材目录不存在: {plan_dir}")
        print(f"       请在 {materials_dir} 下创建以计划 ID 命名的子目录并放入视频文件。")
        return []

    video_files = []
    for filename in os.listdir(plan_dir):
        _, ext = os.path.splitext(filename)
        if ext.lower() in SUPPORTED_VIDEO_EXTENSIONS:
            filepath = os.path.join(plan_dir, filename)
            if os.path.isfile(filepath):
                video_files.append(filepath)

    video_files.sort()

    if not video_files:
        print(f"[警告] 目录 {plan_dir} 中未找到支持的视频文件。")
        print(f"       支持的格式: {', '.join(sorted(SUPPORTED_VIDEO_EXTENSIONS))}")
    else:
        print(f"[信息] 在 {plan_dir} 中找到 {len(video_files)} 个视频文件。")

    return video_files


def upload_and_wait(client, filepath: str, max_wait: int = 600, poll_interval: int = 5):
    """
    上传视频到 GenAI File API，轮询等待处理完成（状态变为 ACTIVE）。
    max_wait: 最大等待秒数，默认 600 秒。
    返回状态为 ACTIVE 的文件对象。
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"视频文件不存在: {filepath}")

    filename = os.path.basename(filepath)
    file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
    print(f"  [上传] 正在上传 {filename} ({file_size_mb:.1f} MB)...")

    # ---- 推断 MIME 类型 ----
    mime_type, _ = mimetypes.guess_type(filepath)
    if not mime_type or not mime_type.startswith("video/"):
        mime_type = "video/mp4"  # 默认回退

    # ---- 以二进制流方式上传，规避中文文件名导致的 UnicodeEncodeError ----
    # google-genai SDK 在处理含非 ASCII 字符的文件路径时，可能在内部
    # 使用 ASCII 编码导致报错。改为直接传入文件流 + 显式 MIME 类型即可规避。
    with open(filepath, "rb") as f:
        uploaded_file = client.files.upload(
            file=f,
            config={"mime_type": mime_type},
        )
    print(f"  [上传] 上传完成，远程文件名: {uploaded_file.name}")

    # ---- 轮询等待文件处理完成 ----
    elapsed = 0
    while hasattr(uploaded_file, 'state') and uploaded_file.state is not None:
        state_name = uploaded_file.state.name if hasattr(uploaded_file.state, 'name') else str(uploaded_file.state)

        if state_name == "ACTIVE":
            print(f"  [上传] 文件状态: ACTIVE（就绪）")
            break
        elif state_name == "PROCESSING":
            if elapsed >= max_wait:
                raise TimeoutError(f"等待视频处理超时（已等待 {elapsed} 秒）。")
            print(f"  [等待] 文件处理中... 已等待 {elapsed} 秒")
            time.sleep(poll_interval)
            elapsed += poll_interval
            uploaded_file = client.files.get(name=uploaded_file.name)
        else:
            raise RuntimeError(f"文件处理失败，状态: {state_name}")

    return uploaded_file


def parse_single_video(client, uploaded_file, config: dict) -> str:
    """
    调用 Gemini 模型对单个已上传视频进行特征要素解析。
    返回模型生成的特征解析文本。
    """
    from google.genai import types

    model_name = config.get("models", {}).get("parse_model", "gemini-3-flash-preview")
    sys_instr = config.get("prompts", {}).get("parse", {}).get("system_instruction", "")
    user_instr = config.get("prompts", {}).get("parse", {}).get("user_instruction", "")
    temperature = config.get("generation", {}).get("parse_temperature", 0.4)
    max_tokens = config.get("generation", {}).get("parse_max_output_tokens", 65536)

    gen_config = types.GenerateContentConfig(
        system_instruction=sys_instr.strip(),
        temperature=temperature,
        max_output_tokens=max_tokens,
    )

    response = client.models.generate_content(
        model=model_name,
        config=gen_config,
        contents=[uploaded_file, user_instr.strip()],
    )

    return response.text if response.text else ""


def cleanup_uploaded_file(client, uploaded_file) -> None:
    """清理已上传的远程文件，释放云端存储（静默忽略失败）。"""
    try:
        client.files.delete(name=uploaded_file.name)
    except Exception:
        pass


def parse_plan(plan_id: str, config: dict, data: dict, data_path: str = "data.json") -> None:
    """
    解析指定计划下所有未处理的视频素材（主入口函数）。

    流程: 扫描视频 → 跳过已解析 → 逐个上传/推理/保存。
    单个视频失败不影响后续处理。
    """
    if plan_id not in data:
        print(f"[错误] 计划 [{plan_id}] 不存在，请先用 insert 命令录入。")
        return

    plan = data[plan_id]
    if "summarization" not in plan:
        plan["summarization"] = {}

    video_files = get_video_files(plan_id)
    if not video_files:
        return

    # ---- 筛选出待解析的视频（断点续传） ----
    parsed = set(plan["summarization"].keys())
    pending = []
    for fp in video_files:
        fn = os.path.basename(fp)
        if fn in parsed:
            print(f"  [跳过] {fn} — 已有解析结果")
        else:
            pending.append(fp)

    if not pending:
        print(f"[信息] 计划 [{plan_id}] 的所有视频均已解析完成。")
        return

    total = len(video_files)
    print(f"[信息] 共 {total} 个视频，已解析 {total - len(pending)} 个，待解析 {len(pending)} 个。")
    print("=" * 60)

    # ---- 创建 API 客户端 ----
    from config_loader import get_client
    client = get_client(config)

    # ---- 逐个处理 ----
    ok, fail = 0, 0
    for idx, filepath in enumerate(pending, 1):
        filename = os.path.basename(filepath)
        print(f"\n--- [{idx}/{len(pending)}] 正在处理: {filename} ---")

        uploaded_file = None
        try:
            uploaded_file = upload_and_wait(client, filepath)

            print(f"  [解析] 正在调用模型进行特征解析...")
            feature_text = parse_single_video(client, uploaded_file, config)

            plan["summarization"][filename] = feature_text
            data[plan_id] = plan

            # 每完成一个视频立即保存，防止意外中断丢失数据
            if save_data(data, data_path):
                print(f"  [保存] 已保存到 {data_path}")
            else:
                print(f"  [警告] 保存失败，数据仅在内存中。")

            ok += 1
            print(f"  [完成] {filename} 解析成功 ✓")

        except (FileNotFoundError, TimeoutError, RuntimeError) as e:
            print(f"  [错误] {e}")
            fail += 1
        except Exception as e:
            print(f"  [错误] 处理 {filename} 时异常: {type(e).__name__}: {e}")
            fail += 1
        finally:
            if uploaded_file is not None:
                cleanup_uploaded_file(client, uploaded_file)

    # ---- 最终统计 ----
    print("\n" + "=" * 60)
    print(f"[统计] 计划 [{plan_id}] — 成功: {ok}, 失败: {fail}, "
          f"总已解析: {len(plan['summarization'])}/{total}")
    if fail > 0:
        print("       失败的视频可重新运行命令继续处理。")
