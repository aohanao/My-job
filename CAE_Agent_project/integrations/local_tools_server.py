from mcp.server.fastmcp import FastMCP
import datetime
import random
import math

# 初始化 MCP Server
mcp = FastMCP("SimpleTools")

@mcp.tool()
def get_current_time(timezone: str = "Asia/Shanghai") -> str:
    """
    获取当前的真实系统时间和日期。
    适用场景：用户询问"现在几点了"、"今天是几号"、"当前日期"、"现在是什么时候"等。
    不适用：查询工程参数、仿真数据、材料属性等专业问题，请使用知识库检索工具。
    参数: timezone - 时区，默认为亚洲/上海
    """
    now = datetime.datetime.now()
    return f"当前时间是: {now.strftime('%Y年%m月%d日 %H:%M:%S')} ({timezone}时区)"

@mcp.tool()
def simple_calculator(expression: str) -> str:
    """
    计算纯数学表达式并返回结果。
    适用场景：用户需要计算明确的数学题，如面积计算、单位换算、简单代数等。
    例如: '12 * 45', '(3.14 * 10**2)', 'math.sin(math.pi/6)'
    支持的运算符: +, -, *, /, **, 括号, 以及 math 模块中的函数(sin/cos/sqrt/pi 等)。
    不适用：查询材料参数、工程规范等，请使用知识库检索工具。
    """
    try:
        allowed_names = {k: v for k, v in math.__dict__.items() if not k.startswith("__")}
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return f"计算结果: {expression} = {result}"
    except Exception as e:
        return f"计算错误: {e}。请检查表达式格式，例如 '12 * 45' 或 'math.pi * 2'"

@mcp.tool()
def get_mock_weather(city: str) -> str:
    """
    查询指定城市的当前天气状况（模拟数据，仅供测试）。
    适用场景：用户询问某个城市的天气、气温、是否下雨等生活类问题。
    例如：用户说"北京天气怎么样"、"上海今天热吗"。
    不适用：工程、仿真、材料、CAE 相关的专业问题。
    参数: city - 城市名称，如"北京"、"上海"、"深圳"
    """
    weathers = ["晴天 🌞", "下雨 🌧️", "多云 ⛅", "下雪 ❄️", "雷阵雨 ⛈️"]
    weather = random.choice(weathers)
    temp = random.randint(-10, 35)
    return f"{city} 当前天气: {weather}，气温 {temp}°C（此为模拟数据，仅供测试）"

if __name__ == "__main__":
    mcp.run(transport='stdio')
