import os
import streamlit as st
from pathlib import Path
from config.settings import settings

st.set_page_config(
    page_title="产品图批量背景替换工具",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🖼️ 产品图批量背景替换工具")
st.markdown("---")

with st.sidebar:
    st.header("⚙️ 配置")

    st.subheader("API 配置")
    api_key = st.text_input(
        "火山方舟 API Key",
        type="password",
        value=os.getenv("ARK_API_KEY", ""),
        help="请输入你的火山方舟 API Key",
    )

    if api_key:
        os.environ["ARK_API_KEY"] = api_key

    st.markdown("---")

    st.subheader("目录信息")
    st.info(f"输入目录: `{settings.INPUT_DIR}`")
    st.info(f"输出目录: `{settings.OUTPUT_DIR}`")

    st.markdown("---")

    st.subheader("使用说明")
    st.markdown("""
    1. 配置 API Key
    2. 将图片放入 `input/` 目录
    3. 输入背景提示词
    4. 点击开始处理
    5. 查看处理结果
    """)

col1, col2 = st.columns([2, 1])

with col1:
    st.header("📝 背景提示词")
    prompt = st.text_area(
        "输入背景描述",
        value="简约白色背景，柔和光影，电商产品摄影风格",
        height=100,
        help="描述你想要的背景风格",
    )

    st.markdown("---")

    st.header("📁 图片管理")

    input_files = list(Path(settings.INPUT_DIR).glob("*"))
    input_files = [
        f for f in input_files if f.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]
    ]

    if input_files:
        st.success(f"发现 {len(input_files)} 张待处理图片")

        with st.expander("查看待处理图片"):
            cols = st.columns(4)
            for idx, img_path in enumerate(input_files[:8]):
                with cols[idx % 4]:
                    st.image(
                        str(img_path), caption=img_path.name, use_column_width=True
                    )

            if len(input_files) > 8:
                st.info(f"还有 {len(input_files) - 8} 张图片未显示")
    else:
        st.warning("没有找到待处理图片，请将图片放入 `input/` 目录")

with col2:
    st.header("🚀 操作")

    if st.button(
        "开始处理",
        type="primary",
        use_container_width=True,
        disabled=not input_files or not prompt or not api_key,
    ):
        st.info("处理功能需要完整的异步支持，请使用命令行版本：")
        st.code(f'python3 main.py "{prompt}"')

    st.markdown("---")

    st.header("📊 处理结果")

    output_files = list(Path(settings.OUTPUT_DIR).glob("*"))
    output_files = [
        f
        for f in output_files
        if f.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]
    ]

    if output_files:
        st.success(f"已生成 {len(output_files)} 张图片")

        with st.expander("查看处理结果"):
            cols = st.columns(4)
            for idx, img_path in enumerate(output_files[:8]):
                with cols[idx % 4]:
                    st.image(
                        str(img_path), caption=img_path.name, use_column_width=True
                    )

            if len(output_files) > 8:
                st.info(f"还有 {len(output_files) - 8} 张图片未显示")
    else:
        st.info("暂无处理结果")

st.markdown("---")
st.markdown("### 📋 处理日志")

log_container = st.container()

with log_container:
    if os.path.exists(settings.LOG_DIR):
        log_files = list(Path(settings.LOG_DIR).glob("*.log"))
        if log_files:
            latest_log = max(log_files, key=lambda p: p.stat().st_mtime)
            with open(latest_log, "r", encoding="utf-8") as f:
                log_content = f.read()
                st.text_area(
                    "最新日志", value=log_content[-5000:], height=200, disabled=True
                )
        else:
            st.info("暂无日志文件")
    else:
        st.info("日志目录不存在")
