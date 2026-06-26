"""单元测试 - 技能自动沉淀与封装中枢"""
import os
import shutil
import pytest
from core.skill_harvester import harvest_new_skill
from core.skills import get_skill, load_skills

SAMPLE_CAE_SCRIPT = """# -*- coding: utf-8 -*-
# Abaqus Python script for bolt preloading simulation
from abaqus import *
from abaqusConstants import *

# Geometry Parameters
bolt_length = 80.0
bolt_radius = 10.0

# Material Parameters
elastic_modulus = 210000.0
density = 7.8e-9

# Loading (Preload Force in N)
preload_force = 15000.0

# Define Model and Part
model = mdb.Model(name='BoltPreloadModel')
s = model.ConstrainedSketch(name='__profile__', sheetSize=200.0)
s.CircleByCenterPerimeter(center=(0.0, 0.0), point=(bolt_radius, 0.0))
# Extrude
p = model.Part(name='Bolt', dimensionality=THREE_D, type=DEFORMABLE_BODY)
p.BaseSolidExtrude(sketch=s, depth=bolt_length)

# Define Step
model.StaticStep(name='Step-1', previous='Initial')

# Apply Bolt Load
# (In real CAE we select faces, here we simulate macro recording)
print("Abaqus Model created successfully. Bolt length = %f, load = %f" % (bolt_length, preload_force))
"""

def test_harvest_bolt_preload():
    """测试将一个成功的螺栓预紧力仿真脚本自动沉淀为智能体 Skill 插件"""
    skill_id = "bolt_preload_test"
    skill_name = "螺栓预紧力三维仿真"
    description = "用于分析螺栓在预紧力作用下的应力变形及松弛行为的仿真"
    
    # 确保没有残留
    target_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "skills", skill_id)
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)

    try:
        # 执行自动沉淀
        res = harvest_new_skill(
            script_content=SAMPLE_CAE_SCRIPT,
            skill_id=skill_id,
            skill_name=skill_name,
            description=description
        )
        
        # 1. 验证接口返回成功
        assert res["status"] == "success", f"技能沉淀失败: {res.get('message')}"
        assert res["skill_id"] == skill_id
        
        # 2. 验证物理文件是否成功创建
        assert os.path.exists(target_dir)
        assert os.path.exists(os.path.join(target_dir, "schema.py"))
        assert os.path.exists(os.path.join(target_dir, "validator.py"))
        assert os.path.exists(os.path.join(target_dir, "tdd_test.py"))
        assert os.path.exists(os.path.join(target_dir, "skill.md"))
        assert os.path.exists(os.path.join(target_dir, "references", "abaqus_macro.jinja2"))
        
        # 3. 验证主 Planner 能否动态识别并加载该新技能
        skills_dict = load_skills(force_reload=True)
        assert skill_id in skills_dict
        
        skill_info = get_skill(skill_id)
        assert skill_info["name"] == skill_name
        assert len(skill_info["trigger_conditions"]) > 0
        assert len(skill_info["few_shot_examples"]) >= 2
        
    finally:
        # 运行完单元测试后，清理生成的技能文件夹，不污染代码库
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
            
        # 重新加载清空缓存
        load_skills(force_reload=True)
