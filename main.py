import os
import asyncio
import argparse
from engine.batch import BatchProcessor
from utils.logger import logger


def main():
    parser = argparse.ArgumentParser(description="产品图批量背景替换工具")
    parser.add_argument("prompt", help="背景替换提示词")
    parser.add_argument("--input", default="./input", help="输入文件夹路径")
    parser.add_argument("--output", default="./output", help="输出文件夹路径")
    args = parser.parse_args()

    logger.info("=== 产品图批量背景替换工具 ===")
    logger.info(f"背景提示词: {args.prompt}")
    logger.info(f"输入文件夹: {args.input}")
    logger.info(f"输出文件夹: {args.output}")

    processor = BatchProcessor(
        args.prompt, input_path=args.input, output_path=args.output
    )
    asyncio.run(processor.process_all())

    logger.info("=== 处理完成 ===")


if __name__ == "__main__":
    main()
