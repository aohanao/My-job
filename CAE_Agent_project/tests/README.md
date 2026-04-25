# CAE Agent 测试文档

## 概述

本测试套件为CAE Agent项目提供完整的测试覆盖，包括单元测试、集成测试和端到端测试。

## 测试分层策略

### 1. 单元测试 (tests/unit/)
测试独立的函数和类，不依赖外部服务。

- **test_validators.py**: 技能参数验证器测试
- **test_routing.py**: 路由决策逻辑测试
- **test_nodes.py**: 各节点的独立逻辑测试
- **test_memory.py**: 记忆系统测试

### 2. 集成测试 (tests/integration/)
测试多个模块的协同工作。

- **test_skill_pipeline.py**: 仿真流水线集成测试
- **test_state_management.py**: 状态管理和传递测试
- **test_tool_integration.py**: 工具集成测试

### 3. 端到端测试 (tests/e2e/)
测试完整的用户场景和工作流。

- **test_chat_workflow.py**: 聊天工作流测试
- **test_simulation_workflow.py**: 仿真工作流测试

## 运行测试

### 运行所有测试
```bash
pytest tests/ -v
```

### 运行特定层级的测试
```bash
# 单元测试
pytest tests/unit/ -v

# 集成测试
pytest tests/integration/ -v

# 端到端测试
pytest tests/e2e/ -v
```

### 运行特定测试文件
```bash
pytest tests/unit/test_validators.py -v
```

### 运行特定测试类或方法
```bash
# 运行特定测试类
pytest tests/unit/test_validators.py::TestBulletImpactValidator -v

# 运行特定测试方法
pytest tests/unit/test_validators.py::TestBulletImpactValidator::test_valid_params -v
```

### 使用标记运行测试
```bash
# 运行单元测试
pytest -m unit

# 运行集成测试
pytest -m integration

# 运行端到端测试
pytest -m e2e

# 跳过慢速测试
pytest -m "not slow"
```

## 生成覆盖率报告

### 生成终端报告
```bash
pytest tests/ --cov=core --cov=skills --cov=integrations --cov-report=term
```

### 生成HTML报告
```bash
pytest tests/ --cov=core --cov=skills --cov=integrations --cov-report=html
```

HTML报告将生成在 `htmlcov/` 目录，用浏览器打开 `htmlcov/index.html` 查看。

### 生成XML报告（用于CI）
```bash
pytest tests/ --cov=core --cov=skills --cov=integrations --cov-report=xml
```

## Mock策略

### 1. Mock LLM
所有测试都使用Mock LLM，避免真实API调用：

```python
from tests.fixtures.mock_llm import create_mock_llm

# 创建带预定义响应的Mock LLM
mock_llm = create_mock_llm(responses=[
    {"content": "这是第一个响应"},
    {"content": "这是第二个响应"}
])
```

### 2. Mock外部服务
- **Abaqus Bridge**: 使用 `responses` 库mock HTTP调用
- **MCP Server**: 使用mock工具和响应
- **Chroma数据库**: 使用临时目录

### 3. 隔离测试环境
- 使用 `temp_dir` fixture创建临时目录
- 使用 `monkeypatch` 修改环境变量和配置
- 每个测试后自动清理

## 添加新测试

### 1. 为新技能添加验证器测试

在 `tests/unit/test_validators.py` 中添加新的测试类：

```python
class TestNewSkillValidator:
    """测试新技能验证器"""
    
    def test_valid_params(self):
        from skills.new_skill.validator import validate
        errors = validate(VALID_PARAMS)
        assert errors == []
```

### 2. 为新节点添加测试

在 `tests/unit/test_nodes.py` 中添加测试：

```python
def test_new_node(mock_llm, initial_state):
    from core.state_graph.nodes.new_node import new_node
    result = new_node(initial_state)
    assert result["some_field"] == expected_value
```

### 3. 添加集成测试

在 `tests/integration/` 中创建新文件或添加到现有文件。

## 最佳实践

### 1. 测试命名
- 测试文件: `test_<module_name>.py`
- 测试类: `Test<FeatureName>`
- 测试方法: `test_<what_it_tests>`

### 2. 测试结构
使用 AAA 模式：
- **Arrange**: 准备测试数据和环境
- **Act**: 执行被测试的代码
- **Assert**: 验证结果

```python
def test_example():
    # Arrange
    state = {"param": "value"}
    
    # Act
    result = function_under_test(state)
    
    # Assert
    assert result == expected_value
```

### 3. 使用Fixtures
利用 `conftest.py` 中的共享fixtures：

```python
def test_with_fixtures(temp_dir, mock_llm, sample_bullet_impact_params):
    # 使用fixtures进行测试
    pass
```

### 4. 参数化测试
对于多个相似的测试用例，使用参数化：

```python
@pytest.mark.parametrize("input,expected", [
    (1, 2),
    (2, 4),
    (3, 6),
])
def test_multiply_by_two(input, expected):
    assert input * 2 == expected
```

### 5. 异步测试
使用 `pytest-asyncio` 测试异步代码：

```python
@pytest.mark.asyncio
async def test_async_function():
    result = await async_function()
    assert result == expected
```

## 持续集成

测试应该在CI/CD流程中自动运行。示例GitHub Actions配置：

```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt
      - run: pytest tests/ --cov=core --cov=skills --cov=integrations --cov-report=xml
      - uses: codecov/codecov-action@v2
```

## 覆盖率目标

- **单元测试**: > 80%
- **集成测试**: 覆盖关键流程
- **端到端测试**: 覆盖主要用户场景

## 故障排查

### 测试失败
1. 查看详细错误信息: `pytest -vv`
2. 查看完整traceback: `pytest --tb=long`
3. 进入调试模式: `pytest --pdb`

### 导入错误
确保项目根目录在Python路径中：
```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
pytest tests/
```

### 环境问题
使用虚拟环境隔离依赖：
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 贡献指南

添加新功能时，请同时添加相应的测试：
1. 新功能 → 单元测试
2. 模块集成 → 集成测试
3. 用户场景 → 端到端测试

确保所有测试通过后再提交代码。
