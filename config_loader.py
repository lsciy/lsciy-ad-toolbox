# ============================================================
# config_loader.py — 配置文件加载与环境初始化模块
# 本模块负责：
# 1. 从 config.toml 读取配置项（代理、API Key、模型名、提示词等）
# 2. 将代理地址注入到系统环境变量中（HTTP_PROXY / HTTPS_PROXY）
# 3. 创建并返回 Google GenAI 客户端实例
# ============================================================

import os
import sys
import tomllib  # Python 3.11+ 内置的 TOML 解析库


def load_config(config_path: str = "config.toml") -> dict:
    """
    加载 TOML 格式的配置文件并返回解析后的字典。

    参数:
        config_path: 配置文件路径，默认为当前目录下的 config.toml

    返回:
        dict: 解析后的配置字典

    异常处理:
        - 文件不存在时打印提示并退出
        - TOML 格式错误时打印具体错误位置并退出
    """
    # ---- 检查配置文件是否存在 ----
    if not os.path.isfile(config_path):
        print(f"[错误] 配置文件不存在: {config_path}")
        print("       请确认 config.toml 文件位于项目根目录下。")
        sys.exit(1)

    try:
        # ---- 以二进制模式读取（tomllib 要求） ----
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        print(f"[信息] 已成功加载配置文件: {config_path}")
        return config

    except tomllib.TOMLDecodeError as e:
        # TOML 语法错误，打印具体的解析错误信息帮助用户定位问题
        print(f"[错误] 配置文件格式不正确: {e}")
        print("       请检查 config.toml 的语法是否符合 TOML 规范。")
        sys.exit(1)

    except PermissionError:
        print(f"[错误] 没有权限读取配置文件: {config_path}")
        sys.exit(1)


def setup_proxy(config: dict) -> None:
    """
    从配置中读取代理地址，并注入到系统环境变量中。
    Google GenAI SDK 底层使用 httpx，会自动从环境变量读取代理设置。

    参数:
        config: 已加载的配置字典

    注意:
        - 此函数必须在创建 genai.Client() 之前调用
        - 代理格式示例: "127.0.0.1:7897"
        - 会同时设置 HTTP_PROXY 和 HTTPS_PROXY（大写和小写都设置，兼容不同库）
    """
    # ---- 从配置中获取代理地址 ----
    proxy_address = config.get("proxy", {}).get("address", "")

    if not proxy_address:
        print("[警告] 配置文件中未设置代理地址，将不使用代理。")
        return

    # ---- 构造完整的代理 URL ----
    # 如果用户没有写协议前缀，自动补上 http://
    if not proxy_address.startswith(("http://", "https://", "socks")):
        proxy_url = f"http://{proxy_address}"
    else:
        proxy_url = proxy_address

    # ---- 同时设置大写和小写的环境变量，确保兼容性 ----
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url
    os.environ["http_proxy"] = proxy_url
    os.environ["https_proxy"] = proxy_url

    print(f"[信息] 已设置网络代理: {proxy_url}")


def get_client(config: dict):
    """
    根据配置创建并返回 Google GenAI 客户端实例。

    参数:
        config: 已加载的配置字典

    返回:
        genai.Client: 已配置 API Key 的客户端实例

    异常处理:
        - API Key 未配置或为默认占位符时打印提示并退出
        - SDK 导入失败时提示安装依赖
    """
    # ---- 检查 API Key 是否已配置 ----
    api_key = config.get("api", {}).get("gemini_api_key", "")

    if not api_key or api_key == "在此处填写你的 Gemini API Key":
        print("[错误] 请在 config.toml 中配置有效的 Gemini API Key。")
        print("       获取方式: https://aistudio.google.com/apikey")
        sys.exit(1)

    # ---- 尝试导入 Google GenAI SDK ----
    try:
        from google import genai
    except ImportError:
        print("[错误] 未安装 google-genai SDK。")
        print("       请在虚拟环境中运行: pip install google-genai")
        sys.exit(1)

    # ---- 创建客户端实例 ----
    try:
        client = genai.Client(api_key=api_key)
        print("[信息] 已成功创建 Gemini API 客户端。")
        return client

    except Exception as e:
        print(f"[错误] 创建 API 客户端失败: {e}")
        sys.exit(1)
