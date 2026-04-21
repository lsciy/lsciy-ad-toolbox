# ============================================================
# main.py — CLI 主入口脚本
# 短视频广告素材要素分析与总结系统
#
# 提供三个子命令：
#   insert    — 录入/更新广告计划数据
#   parse     — 解析计划下的视频素材特征
#   summarize — 按条件筛选并归纳总结素材特征
#
# 使用示例：
#   python main.py insert --plan_id "123" --category "美妆" --type "口红"
#   python main.py parse --plan_id "123"
#   python main.py summarize --category "美妆" --min_roi 1.2
# ============================================================

import argparse
import sys

from config_loader import load_config, setup_proxy
from data_manager import load_data, save_data, upsert_plan


def build_parser() -> argparse.ArgumentParser:
    """
    构建命令行参数解析器，包含三个子命令及其各自的参数定义。
    """
    # ---- 顶层解析器 ----
    parser = argparse.ArgumentParser(
        prog="ad-toolbox",
        description="短视频广告素材要素分析与总结系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python main.py insert --plan_id "123" --category "美妆" --type "口红" --cpm 20.5 --ctr 0.05 --cvr 0.02 --roi 1.5
  python main.py parse --plan_id "123"
  python main.py summarize --category "美妆" --min_roi 1.2 --max_cpm 50
        """
    )
    parser.add_argument(
        "--config", default="config.toml",
        help="配置文件路径（默认: config.toml）"
    )
    parser.add_argument(
        "--data", default="data.json",
        help="数据文件路径（默认: data.json）"
    )

    subparsers = parser.add_subparsers(dest="command", help="可用的子命令")

    # ==============================
    # 子命令 1: insert — 数据录入
    # ==============================
    insert_parser = subparsers.add_parser(
        "insert", help="录入或更新广告计划数据",
        description="将广告计划的基本信息和效果数据录入到 data.json 中。"
    )
    insert_parser.add_argument("--plan_id", required=True, help="计划 ID（必填）")
    insert_parser.add_argument("--category", default=None, help="产品类目（如: 美妆、食品）")
    insert_parser.add_argument("--type", default=None, help="产品类型（如: 口红、面膜）")
    insert_parser.add_argument("--cpm", type=float, default=None, help="千次展示成本 (CPM)")
    insert_parser.add_argument("--ctr", type=float, default=None, help="点击率 (CTR)")
    insert_parser.add_argument("--cvr", type=float, default=None, help="转化率 (CVR)")
    insert_parser.add_argument("--roi", type=float, default=None, help="投资回报率 (ROI)")

    # ==============================
    # 子命令 2: parse — 视频解析
    # ==============================
    parse_parser = subparsers.add_parser(
        "parse", help="解析计划下的视频素材特征",
        description="调用 Gemini 模型对指定计划的视频素材进行特征要素解析。"
    )
    parse_parser.add_argument("--plan_id", required=True, help="计划 ID（必填）")

    # ==============================
    # 子命令 3: summarize — 归纳总结
    # ==============================
    sum_parser = subparsers.add_parser(
        "summarize", help="按条件筛选并归纳总结素材特征",
        description="筛选高效果计划，调用 Gemini 模型归纳总结共性特征和优化建议。"
    )
    # 字符串筛选
    sum_parser.add_argument("--category", default=None, help="按产品类目筛选（精确匹配）")
    sum_parser.add_argument("--type", default=None, help="按产品类型筛选（精确匹配）")
    # 数值范围筛选 — 每个数值字段都支持大于(min)和小于(max)
    sum_parser.add_argument("--min_cpm", type=float, default=None, help="CPM 最小值（>=）")
    sum_parser.add_argument("--max_cpm", type=float, default=None, help="CPM 最大值（<=）")
    sum_parser.add_argument("--min_ctr", type=float, default=None, help="CTR 最小值（>=）")
    sum_parser.add_argument("--max_ctr", type=float, default=None, help="CTR 最大值（<=）")
    sum_parser.add_argument("--min_cvr", type=float, default=None, help="CVR 最小值（>=）")
    sum_parser.add_argument("--max_cvr", type=float, default=None, help="CVR 最大值（<=）")
    sum_parser.add_argument("--min_roi", type=float, default=None, help="ROI 最小值（>=）")
    sum_parser.add_argument("--max_roi", type=float, default=None, help="ROI 最大值（<=）")
    sum_parser.add_argument("--min_ecpm", type=float, default=None, help="eCPM 最小值（>=）")
    sum_parser.add_argument("--max_ecpm", type=float, default=None, help="eCPM 最大值（<=）")

    return parser


def handle_insert(args, data: dict, data_path: str) -> None:
    """处理 insert 子命令：录入或更新计划数据。"""
    upsert_plan(
        data,
        plan_id=args.plan_id,
        product_category=args.category,
        product_type=args.type,
        CPM=args.cpm,
        CTR=args.ctr,
        CVR=args.cvr,
        ROI=args.roi,
    )

    if save_data(data, data_path):
        print(f"[信息] 数据已保存到 {data_path}")
    else:
        print(f"[错误] 保存数据失败！")
        sys.exit(1)


def handle_parse(args, config: dict, data: dict, data_path: str) -> None:
    """处理 parse 子命令：解析视频素材。"""
    from video_parser import parse_plan
    parse_plan(args.plan_id, config, data, data_path)


def handle_summarize(args, config: dict, data: dict) -> None:
    """处理 summarize 子命令：归纳总结。"""
    from summarizer import summarize_command

    # ---- 将所有筛选参数传入 ----
    summarize_command(
        config, data,
        category=args.category,
        type=args.type,
        min_cpm=args.min_cpm, max_cpm=args.max_cpm,
        min_ctr=args.min_ctr, max_ctr=args.max_ctr,
        min_cvr=args.min_cvr, max_cvr=args.max_cvr,
        min_roi=args.min_roi, max_roi=args.max_roi,
        min_ecpm=args.min_ecpm, max_ecpm=args.max_ecpm,
    )


def main():
    """程序主入口。"""
    parser = build_parser()
    args = parser.parse_args()

    # ---- 未指定子命令时打印帮助 ----
    if not args.command:
        parser.print_help()
        sys.exit(0)

    # ---- 步骤 1: 加载配置文件 ----
    config = load_config(args.config)

    # ---- 步骤 2: 注入网络代理 ----
    setup_proxy(config)

    # ---- 步骤 3: 加载数据文件 ----
    data = load_data(args.data)

    # ---- 步骤 4: 路由到对应的子命令处理函数 ----
    try:
        if args.command == "insert":
            handle_insert(args, data, args.data)

        elif args.command == "parse":
            handle_parse(args, config, data, args.data)

        elif args.command == "summarize":
            handle_summarize(args, config, data)

    except KeyboardInterrupt:
        print("\n[信息] 用户中断操作。已处理的数据不受影响。")
        sys.exit(0)

    except Exception as e:
        print(f"\n[致命错误] {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
