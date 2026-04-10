import streamlit as st

st.title("测试页面")
st.write("如果你能看到这个页面，说明 Streamlit 运行正常！")

st.text_input("输入测试", value="Hello World")
st.button("点击测试")

if st.button("显示信息"):
    st.success("按钮工作正常！")