"""示例参数数据 - 用于测试各技能的参数验证"""


# ============ Bullet Impact 技能参数 ============

VALID_BULLET_IMPACT_PARAMS = {
    "status": "success",
    "message": "",
    "geometry": {
        "plate_length": 200.0,
        "plate_thickness": 20.0,
        "bullet_radius": 20.0
    },
    "material": {
        "density": 7.85e-9,
        "elastic_modulus": 210000.0
    },
    "physics": {
        "step_time": 0.01
    }
}

INVALID_BULLET_IMPACT_PARAMS_NEGATIVE_THICKNESS = {
    "status": "success",
    "message": "",
    "geometry": {
        "plate_length": 200.0,
        "plate_thickness": -5.0,  # 负值
        "bullet_radius": 20.0
    },
    "material": {
        "density": 7.85e-9,
        "elastic_modulus": 210000.0
    },
    "physics": {
        "step_time": 0.01
    }
}

INVALID_BULLET_IMPACT_PARAMS_OVERSIZED_BULLET = {
    "status": "success",
    "message": "",
    "geometry": {
        "plate_length": 100.0,
        "plate_thickness": 20.0,
        "bullet_radius": 60.0  # 直径120 > 板长100
    },
    "material": {
        "density": 7.85e-9,
        "elastic_modulus": 210000.0
    },
    "physics": {
        "step_time": 0.01
    }
}

INVALID_BULLET_IMPACT_PARAMS_NEGATIVE_MODULUS = {
    "status": "success",
    "message": "",
    "geometry": {
        "plate_length": 200.0,
        "plate_thickness": 20.0,
        "bullet_radius": 20.0
    },
    "material": {
        "density": 7.85e-9,
        "elastic_modulus": -1000.0  # 负值
    },
    "physics": {
        "step_time": 0.01
    }
}

BOUNDARY_BULLET_IMPACT_PARAMS = {
    "status": "success",
    "message": "",
    "geometry": {
        "plate_length": 1.0,  # 极小值
        "plate_thickness": 0.1,
        "bullet_radius": 0.1
    },
    "material": {
        "density": 1e-10,
        "elastic_modulus": 1.0
    },
    "physics": {
        "step_time": 0.001
    }
}


# ============ Tunnel Support 技能参数 ============

VALID_TUNNEL_SUPPORT_PARAMS = {
    "status": "success",
    "message": "",
    "excavation_method": "全断面法",
    "anchor_length": 6.0,
    "shotcrete_thickness": 25.0,
    "equipment_config": ["掘进机", "喷射机"],
    "reasoning": "基于III级围岩标准"
}

INVALID_TUNNEL_SUPPORT_PARAMS_NEGATIVE_ANCHOR = {
    "status": "success",
    "message": "",
    "excavation_method": "台阶法",
    "anchor_length": -2.0,  # 负值
    "shotcrete_thickness": 25.0,
    "equipment_config": ["掘进机"],
    "reasoning": "测试负值"
}

INVALID_TUNNEL_SUPPORT_PARAMS_OVERSIZED_ANCHOR = {
    "status": "success",
    "message": "",
    "excavation_method": "CD法",
    "anchor_length": 25.0,  # 超过20m
    "shotcrete_thickness": 30.0,
    "equipment_config": ["掘进机"],
    "reasoning": "测试超量纲"
}

INVALID_TUNNEL_SUPPORT_PARAMS_OVERSIZED_SHOTCRETE = {
    "status": "success",
    "message": "",
    "excavation_method": "全断面法",
    "anchor_length": 8.0,
    "shotcrete_thickness": 150.0,  # 超过100cm
    "equipment_config": ["掘进机", "喷射机"],
    "reasoning": "测试超厚混凝土"
}

BOUNDARY_TUNNEL_SUPPORT_PARAMS = {
    "status": "success",
    "message": "",
    "excavation_method": "台阶法",
    "anchor_length": 0.1,  # 极小值
    "shotcrete_thickness": 0.1,
    "equipment_config": ["基础设备"],
    "reasoning": "边界测试"
}


# ============ 需要追问的参数 ============

NEED_CLARIFICATION_PARAMS = {
    "status": "need_clarification",
    "message": "请提供钢板的厚度参数",
    "geometry": {
        "plate_length": 200.0,
        "plate_thickness": 0.0,
        "bullet_radius": 20.0
    },
    "material": {
        "density": 7.85e-9,
        "elastic_modulus": 210000.0
    },
    "physics": {
        "step_time": 0.01
    }
}
