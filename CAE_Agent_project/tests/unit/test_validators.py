"""单元测试 - 技能验证器"""
import pytest
from tests.fixtures.sample_params import (
    VALID_BULLET_IMPACT_PARAMS,
    INVALID_BULLET_IMPACT_PARAMS_NEGATIVE_THICKNESS,
    INVALID_BULLET_IMPACT_PARAMS_OVERSIZED_BULLET,
    INVALID_BULLET_IMPACT_PARAMS_NEGATIVE_MODULUS,
    VALID_TUNNEL_SUPPORT_PARAMS,
    INVALID_TUNNEL_SUPPORT_PARAMS_NEGATIVE_ANCHOR,
    INVALID_TUNNEL_SUPPORT_PARAMS_OVERSIZED_ANCHOR,
    INVALID_TUNNEL_SUPPORT_PARAMS_OVERSIZED_SHOTCRETE,
)


class TestBulletImpactValidator:
    """测试子弹冲击验证器"""

    def test_valid_params(self):
        """测试有效参数"""
        from skills.bullet_impact.validator import validate
        errors = validate(VALID_BULLET_IMPACT_PARAMS)
        assert errors == [], f"有效参数不应产生错误，但得到: {errors}"

    def test_negative_thickness(self):
        """测试负厚度"""
        from skills.bullet_impact.validator import validate
        errors = validate(INVALID_BULLET_IMPACT_PARAMS_NEGATIVE_THICKNESS)
        assert len(errors) > 0, "负厚度应该产生错误"
        assert any("厚度" in err for err in errors), f"错误消息应包含'厚度'，但得到: {errors}"

    def test_oversized_bullet(self):
        """测试子弹直径超过钢板尺寸"""
        from skills.bullet_impact.validator import validate
        errors = validate(INVALID_BULLET_IMPACT_PARAMS_OVERSIZED_BULLET)
        assert len(errors) > 0, "子弹过大应该产生错误"
        assert any("直径" in err or "尺寸" in err for err in errors), f"错误消息应包含尺寸相关信息，但得到: {errors}"

    def test_negative_elastic_modulus(self):
        """测试负弹性模量"""
        from skills.bullet_impact.validator import validate
        errors = validate(INVALID_BULLET_IMPACT_PARAMS_NEGATIVE_MODULUS)
        assert len(errors) > 0, "负弹性模量应该产生错误"
        assert any("弹性模量" in err for err in errors), f"错误消息应包含'弹性模量'，但得到: {errors}"

    def test_zero_bullet_radius(self):
        """测试零半径子弹"""
        from skills.bullet_impact.validator import validate
        params = VALID_BULLET_IMPACT_PARAMS.copy()
        params["geometry"]["bullet_radius"] = 0
        errors = validate(params)
        assert len(errors) > 0, "零半径应该产生错误"

    def test_negative_step_time(self):
        """测试负步长"""
        from skills.bullet_impact.validator import validate
        params = VALID_BULLET_IMPACT_PARAMS.copy()
        params["physics"]["step_time"] = -0.01
        errors = validate(params)
        assert len(errors) > 0, "负步长应该产生错误"

    def test_multiple_errors(self):
        """测试多个错误同时存在"""
        from skills.bullet_impact.validator import validate
        params = {
            "geometry": {
                "plate_thickness": -5.0,  # 错误1
                "bullet_radius": -10.0,   # 错误2
                "plate_length": 100.0
            },
            "material": {
                "elastic_modulus": -1000.0,  # 错误3
                "density": 7.85e-9
            },
            "physics": {
                "step_time": 0.01
            }
        }
        errors = validate(params)
        assert len(errors) >= 3, f"应该检测到至少3个错误，但只得到: {errors}"


class TestTunnelSupportValidator:
    """测试隧道支护验证器"""

    def test_valid_params(self):
        """测试有效参数"""
        from skills.tunnel_support.validator import validate
        errors = validate(VALID_TUNNEL_SUPPORT_PARAMS)
        assert errors == [], f"有效参数不应产生错误，但得到: {errors}"

    def test_negative_anchor_length(self):
        """测试负锚杆长度"""
        from skills.tunnel_support.validator import validate
        errors = validate(INVALID_TUNNEL_SUPPORT_PARAMS_NEGATIVE_ANCHOR)
        assert len(errors) > 0, "负锚杆长度应该产生错误"
        assert any("锚杆" in err for err in errors), f"错误消息应包含'锚杆'，但得到: {errors}"

    def test_oversized_anchor_length(self):
        """测试超大锚杆长度"""
        from skills.tunnel_support.validator import validate
        errors = validate(INVALID_TUNNEL_SUPPORT_PARAMS_OVERSIZED_ANCHOR)
        assert len(errors) > 0, "超大锚杆长度应该产生错误"
        assert any("锚杆" in err and "20m" in err for err in errors), f"错误消息应包含锚杆和20m限制，但得到: {errors}"

    def test_oversized_shotcrete_thickness(self):
        """测试超厚混凝土"""
        from skills.tunnel_support.validator import validate
        errors = validate(INVALID_TUNNEL_SUPPORT_PARAMS_OVERSIZED_SHOTCRETE)
        assert len(errors) > 0, "超厚混凝土应该产生错误"
        assert any("混凝土" in err or "厚度" in err for err in errors), f"错误消息应包含混凝土或厚度，但得到: {errors}"

    def test_zero_anchor_length(self):
        """测试零锚杆长度"""
        from skills.tunnel_support.validator import validate
        params = VALID_TUNNEL_SUPPORT_PARAMS.copy()
        params["anchor_length"] = 0
        errors = validate(params)
        assert len(errors) > 0, "零锚杆长度应该产生错误"

    def test_boundary_values(self):
        """测试边界值"""
        from skills.tunnel_support.validator import validate

        # 测试最小有效值
        params = VALID_TUNNEL_SUPPORT_PARAMS.copy()
        params["anchor_length"] = 0.1
        params["shotcrete_thickness"] = 0.1
        errors = validate(params)
        assert errors == [], "边界最小值应该有效"

        # 测试最大有效值
        params["anchor_length"] = 20.0
        params["shotcrete_thickness"] = 100.0
        errors = validate(params)
        assert errors == [], "边界最大值应该有效"

        # 测试刚好超出边界
        params["anchor_length"] = 20.1
        errors = validate(params)
        assert len(errors) > 0, "刚好超出边界应该产生错误"


class TestValidatorEdgeCases:
    """测试验证器的边界情况"""

    def test_missing_fields(self):
        """测试缺失字段"""
        from skills.bullet_impact.validator import validate

        # 缺失geometry字段
        params = {
            "material": {"elastic_modulus": 210000.0},
            "physics": {"step_time": 0.01}
        }
        # 验证器应该能处理缺失字段（使用默认值或返回错误）
        errors = validate(params)
        # 不应该抛出异常

    def test_empty_params(self):
        """测试空参数"""
        from skills.bullet_impact.validator import validate
        errors = validate({})
        # 不应该抛出异常

    def test_none_values(self):
        """测试None值"""
        from skills.bullet_impact.validator import validate
        params = VALID_BULLET_IMPACT_PARAMS.copy()
        params["geometry"]["plate_thickness"] = None
        # 不应该抛出异常
        try:
            errors = validate(params)
        except Exception as e:
            pytest.fail(f"验证器不应该在None值时抛出异常: {e}")
