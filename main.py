#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园跑步数据生成器 - 主程序
用于生成校园跑步数据的运动数据文件（默认 FIT，兼容 TCX）

作者: 猫娘幽浮喵
功能:
1. 根据时间范围和每日公里数范围生成数据文件
2. 根据时间和总公里数生成匹配数据的数据文件
3. 配速、总公里数、跑步开始时间范围可自定义
4. 支持多轨迹和预设模板
"""

import os
import sys
import argparse
import datetime
import logging

# 解决Windows控制台中文乱码问题
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())

# 导入自定义模块
from src.config_manager import ConfigManager
from src.template_manager import TemplateManager
from src.generation_engine import GenerationEngine


def setup_logging(verbose: bool = False):
    """配置日志"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def generate_by_daily_range(args, engine: GenerationEngine, template_manager: TemplateManager):
    """根据每日公里数范围生成数据文件"""
    print("=" * 60)
    print("根据每日公里数范围生成数据文件")
    print("=" * 60)

    # 构建配置
    overrides = {
        "min_pace": args.min_pace,
        "max_pace": args.max_pace,
        "start_time_min": args.start_time_min,
        "start_time_max": args.start_time_max,
        "output_dir": args.output_dir,
        "include_track": not args.no_track,
        "apply_correction": not args.no_correction,
        "enable_pace_fluctuation": not args.no_pace_fluctuation,
        "create_zip": args.zip,
    }
    if args.track:
        overrides["track_id"] = args.track
    if args.format:
        overrides["output_format"] = args.format

    config = template_manager.apply_template(
        template_id=args.template,
        overrides=overrides
    )

    # 解析日期
    start_date = datetime.datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_date = datetime.datetime.strptime(args.end_date, "%Y-%m-%d").date()

    # 生成
    results = engine.generate_daily(start_date, end_date, args.min_km, args.max_km, config)

    print(f"\n任务完成！")
    print(f"生成的文件: {len(results)}个")
    print(f"输出目录: {args.output_dir}")
    print(f"包含轨迹: {'否' if args.no_track else '是'}")

    return [r.filepath for r in results]


def generate_by_total_km(args, engine: GenerationEngine, template_manager: TemplateManager):
    """根据总公里数生成匹配数据的数据文件"""
    print("=" * 60)
    print("根据总公里数生成匹配数据的数据文件")
    print("=" * 60)

    # 构建配置
    overrides = {
        "min_pace": args.min_pace,
        "max_pace": args.max_pace,
        "start_time_min": args.start_time_min,
        "start_time_max": args.start_time_max,
        "output_dir": args.output_dir,
        "include_track": not args.no_track,
        "apply_correction": not args.no_correction,
        "enable_pace_fluctuation": not args.no_pace_fluctuation,
        "create_zip": args.zip,
        "weekend_factor": args.weekend_factor,
        "rest_days_per_week": args.rest_days_per_week,
        "min_daily_km": args.min_daily_km,
        "max_daily_km": args.max_daily_km,
    }
    if args.track:
        overrides["track_id"] = args.track
    if args.format:
        overrides["output_format"] = args.format

    config = template_manager.apply_template(
        template_id=args.template,
        overrides=overrides
    )

    # 解析日期
    start_date = datetime.datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_date = datetime.datetime.strptime(args.end_date, "%Y-%m-%d").date()

    # 生成
    results = engine.generate_total(start_date, end_date, args.total_km, config)

    # 打印计划摘要
    planner_results = engine.generate_total.__self__
    print(f"\n跑步计划摘要:")
    print(f"  目标总距离: {args.total_km} 公里")
    print(f"  时间范围: {args.start_date} 至 {args.end_date}")

    print(f"\n任务完成！")
    print(f"生成的文件: {len(results)}个")
    print(f"输出目录: {args.output_dir}")
    print(f"包含轨迹: {'否' if args.no_track else '是'}")

    return [r.filepath for r in results]


def generate_single_file(args, engine: GenerationEngine, template_manager: TemplateManager):
    """生成单个数据文件"""
    print("=" * 60)
    print("生成单个数据文件")
    print("=" * 60)

    # 构建配置
    overrides = {
        "output_dir": args.output_dir,
        "include_track": not args.no_track,
        "apply_correction": not args.no_correction,
        "enable_pace_fluctuation": not args.no_pace_fluctuation,
        "create_zip": args.zip,
    }
    if args.track:
        overrides["track_id"] = args.track
    if args.format:
        overrides["output_format"] = args.format
    if args.pace:
        # 单文件模式使用固定配速
        overrides["min_pace"] = args.pace
        overrides["max_pace"] = args.pace

    # 单文件模式使用固定开始时间
    overrides["start_time_min"] = args.start_time
    overrides["start_time_max"] = args.start_time

    config = template_manager.apply_template(
        template_id=args.template,
        overrides=overrides
    )

    # 解析日期
    date = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()

    # 生成
    result = engine.generate_single(date, args.distance, config)

    print(f"\n任务完成！")
    print(f"生成的文件: {os.path.basename(result.filepath)}")
    print(f"输出目录: {args.output_dir}")
    print(f"包含轨迹: {'否' if args.no_track else '是'}")

    return [result.filepath]


def list_tracks(config_manager: ConfigManager):
    """列出所有可用轨迹"""
    print("可用轨迹:")
    for track_id in config_manager.list_tracks():
        try:
            track = config_manager.load_track(track_id)
            print(f"  {track_id}: {track.name} - {track.description}")
        except Exception as e:
            print(f"  {track_id}: [加载失败] {e}")


def list_templates(template_manager: TemplateManager):
    """列出所有可用模板"""
    print("可用模板:")
    for tmpl in template_manager.list_available():
        print(f"  {tmpl['id']}: {tmpl['name']} - {tmpl['description']}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='校园跑步数据生成器')
    # 全局选项
    parser.add_argument('--list-tracks', action='store_true', help='列出所有可用轨迹')
    parser.add_argument('--list-templates', action='store_true', help='列出所有可用模板')
    parser.add_argument('--track', help='指定轨迹ID（默认: campus_default）')
    parser.add_argument('--template', help='指定预设模板')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细日志')

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # 每日公里数范围生成命令
    daily_parser = subparsers.add_parser('daily', help='根据每日公里数范围生成数据文件')
    daily_parser.add_argument('--start-date', required=True, help='开始日期 (YYYY-MM-DD)')
    daily_parser.add_argument('--end-date', required=True, help='结束日期 (YYYY-MM-DD)')
    daily_parser.add_argument('--min-km', type=float, required=True, help='最低公里数（周内基准）')
    daily_parser.add_argument('--max-km', type=float, required=True, help='最高公里数（周内基准）')
    daily_parser.add_argument('--min-pace', type=float, default=7.0, help='最快配速（分钟/公里） (默认: 7.0)')
    daily_parser.add_argument('--max-pace', type=float, default=8.0, help='最慢配速（分钟/公里） (默认: 8.0)')
    daily_parser.add_argument('--start-time-min', default='06:00', help='最早开始时间 (HH:MM) (默认: 06:00)')
    daily_parser.add_argument('--start-time-max', default='08:00', help='最晚开始时间 (HH:MM) (默认: 08:00)')
    daily_parser.add_argument('--output-dir', default='output', help='输出目录 (默认: output)')
    daily_parser.add_argument('--no-track', action='store_true', help='不生成轨迹点')
    daily_parser.add_argument('--no-correction', action='store_true', help='不应用坐标修正')
    daily_parser.add_argument('--no-pace-fluctuation', action='store_true', help='不应用配速波动')
    daily_parser.add_argument('--format', choices=['tcx', 'fit'], help='输出文件格式 (默认: fit，Keep 导入请用 fit)')
    daily_parser.add_argument('--zip', action='store_true', help='将生成的文件打包成ZIP压缩包')
    daily_parser.add_argument('--track', help='指定轨迹ID')
    daily_parser.add_argument('--template', help='指定预设模板')

    # 总公里数生成命令
    total_parser = subparsers.add_parser('total', help='根据总公里数生成匹配数据的数据文件')
    total_parser.add_argument('--start-date', required=True, help='开始日期 (YYYY-MM-DD)')
    total_parser.add_argument('--end-date', required=True, help='结束日期 (YYYY-MM-DD)')
    total_parser.add_argument('--total-km', type=float, required=True, help='总公里数')
    total_parser.add_argument('--min-daily-km', type=float, default=2.0, help='每日最低公里数 (默认: 2.0)')
    total_parser.add_argument('--max-daily-km', type=float, default=8.0, help='每日最高公里数 (默认: 8.0)')
    total_parser.add_argument('--weekend-factor', type=float, default=1.5, help='周末距离是周内的倍数 (默认: 1.5)')
    total_parser.add_argument('--rest-days-per-week', type=int, default=1, help='每周休息天数 (默认: 1)')
    total_parser.add_argument('--min-pace', type=float, default=7.0, help='最快配速（分钟/公里） (默认: 7.0)')
    total_parser.add_argument('--max-pace', type=float, default=8.0, help='最慢配速（分钟/公里） (默认: 8.0)')
    total_parser.add_argument('--start-time-min', default='06:00', help='最早开始时间 (HH:MM) (默认: 06:00)')
    total_parser.add_argument('--start-time-max', default='08:00', help='最晚开始时间 (HH:MM) (默认: 08:00)')
    total_parser.add_argument('--output-dir', default='output', help='输出目录 (默认: output)')
    total_parser.add_argument('--no-track', action='store_true', help='不生成轨迹点')
    total_parser.add_argument('--no-correction', action='store_true', help='不应用坐标修正')
    total_parser.add_argument('--no-pace-fluctuation', action='store_true', help='不应用配速波动')
    total_parser.add_argument('--format', choices=['tcx', 'fit'], help='输出文件格式 (默认: fit，Keep 导入请用 fit)')
    total_parser.add_argument('--zip', action='store_true', help='将生成的文件打包成ZIP压缩包')
    total_parser.add_argument('--track', help='指定轨迹ID')
    total_parser.add_argument('--template', help='指定预设模板')

    # 单个文件生成命令
    single_parser = subparsers.add_parser('single', help='生成单个数据文件')
    single_parser.add_argument('--date', required=True, help='日期 (YYYY-MM-DD)')
    single_parser.add_argument('--distance', type=float, required=True, help='距离（公里）')
    single_parser.add_argument('--pace', type=float, help='配速（分钟/公里），如果不指定则随机生成')
    single_parser.add_argument('--start-time', default='07:00', help='开始时间 (HH:MM) (默认: 07:00)')
    single_parser.add_argument('--output-dir', default='output', help='输出目录 (默认: output)')
    single_parser.add_argument('--no-track', action='store_true', help='不生成轨迹点')
    single_parser.add_argument('--no-correction', action='store_true', help='不应用坐标修正')
    single_parser.add_argument('--no-pace-fluctuation', action='store_true', help='不应用配速波动')
    single_parser.add_argument('--format', choices=['tcx', 'fit'], help='输出文件格式 (默认: fit，Keep 导入请用 fit)')
    single_parser.add_argument('--zip', action='store_true', help='将生成的文件打包成ZIP压缩包')
    single_parser.add_argument('--track', help='指定轨迹ID')
    single_parser.add_argument('--template', help='指定预设模板')

    args = parser.parse_args()

    # 设置日志
    setup_logging(args.verbose)

    # 初始化管理器
    project_root = os.path.dirname(os.path.abspath(__file__))
    config_manager = ConfigManager(os.path.join(project_root, "config"))
    template_manager = TemplateManager(config_manager)
    engine = GenerationEngine(config_manager)

    # 处理列表命令
    if args.list_tracks:
        list_tracks(config_manager)
        return

    if args.list_templates:
        list_templates(template_manager)
        return

    # 执行生成命令
    if args.command == 'daily':
        generate_by_daily_range(args, engine, template_manager)
    elif args.command == 'total':
        generate_by_total_km(args, engine, template_manager)
    elif args.command == 'single':
        generate_single_file(args, engine, template_manager)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
