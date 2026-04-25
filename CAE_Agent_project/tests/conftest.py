"""pytest配置和共享fixtures"""
import pytest
import os
import sys
import tempfile
import shutil
from pathlib import Path

# 添加项目根目录到Python路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def temp_dir():
    """创建临时目录用于测试"""
    temp_path = tempfile.mkdtemp()
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def mock_env_vars(monkeypatch):
    """设置测试环境变量"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-api-key")
    monkeypatch.setenv("DEFAULT_MODEL", "qwen-turbo")
    monkeypatch.setenv("TOOL_BACKEND", "local")
    monkeypatch.setenv("MAX_PARAM_RETRY", "3")


@pytest.fixture
def sample_bullet_impact_params():
    """子弹冲击技能的示例参数"""
    from tests.fixtures.sample_params import VALID_BULLET_IMPACT_PARAMS
    return VALID_BULLET_IMPACT_PARAMS.copy()


@pytest.fixture
def sample_tunnel_support_params():
    """隧道支护技能的示例参数"""
    from tests.fixtures.sample_params import VALID_TUNNEL_SUPPORT_PARAMS
    return VALID_TUNNEL_SUPPORT_PARAMS.copy()


@pytest.fixture
def initial_state():
    """初始状态"""
    from tests.fixtures.sample_states import INITIAL_STATE
    return INITIAL_STATE.copy()


@pytest.fixture
def mock_llm():
    """创建Mock LLM"""
    from tests.fixtures.mock_llm import MockLLM
    return MockLLM(responses=[])


@pytest.fixture
def mock_scripts_dir(temp_dir, monkeypatch):
    """Mock脚本生成目录"""
    scripts_dir = os.path.join(temp_dir, "generated_scripts")
    os.makedirs(scripts_dir, exist_ok=True)

    # 修改config中的路径
    import core.config as config
    monkeypatch.setattr(config, "SCRIPTS_DIR", scripts_dir)
    monkeypatch.setattr(config, "SANDBOX_DIR", temp_dir)

    return scripts_dir


@pytest.fixture
def mock_chroma_db(temp_dir, monkeypatch):
    """Mock Chroma向量数据库目录"""
    db_dir = os.path.join(temp_dir, "chroma_test")
    os.makedirs(db_dir, exist_ok=True)
    return db_dir


@pytest.fixture(autouse=True)
def reset_module_cache():
    """每个测试后重置模块缓存"""
    yield
    # 清理可能被缓存的模块
    import sys
    modules_to_remove = [k for k in sys.modules.keys() if k.startswith('skills.')]
    for module in modules_to_remove:
        del sys.modules[module]


@pytest.fixture
def suppress_print(monkeypatch):
    """抑制print输出，保持测试输出清洁"""
    import builtins
    monkeypatch.setattr(builtins, 'print', lambda *args, **kwargs: None)
