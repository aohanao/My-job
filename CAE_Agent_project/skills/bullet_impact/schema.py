from pydantic import BaseModel, Field

class GeometrySchema(BaseModel):
    plate_length: float = Field(default=200.0, description="钢板的长和宽，默认 200mm")
    plate_thickness: float = Field(default=20.0, description="钢板的厚度，默认 20mm")
    bullet_radius: float = Field(default=20.0, description="子弹的半径，默认 20mm")

class MaterialSchema(BaseModel):
    density: float = Field(default=7.85e-9, description="材料密度，默认 HPB300锤")
    elastic_modulus: float = Field(default=210000.0, description="材料弹性模量，默认 HPB300锤")

class PhysicsSchema(BaseModel):
    step_time: float = Field(default=0.01, description="显式动力学分析步长")

class SkillSchema(BaseModel):
    """子弹冲击钢板参数骨架"""
    status: str = Field(
        default="success",
        description="参数状态"
    )
    message: str = Field(
        default="",
        description="反馈信息"
    )
    geometry: GeometrySchema
    material: MaterialSchema
    physics: PhysicsSchema
