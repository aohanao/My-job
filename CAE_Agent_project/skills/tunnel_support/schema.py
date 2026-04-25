from pydantic import BaseModel, Field

class SkillSchema(BaseModel):
    """隧道工程支护参数骨架"""
    status: str = Field(
        default="success",
        description="参数状态：'success' 或 'need_clarification'(需追问/修正)"
    )
    message: str = Field(
        default="",
        description="追问或错误说明"
    )
    excavation_method: str = Field(
        description="开挖方法，例如：全断面法、台阶法、CD法等"
    )
    anchor_length: float = Field(
        description="系统锚杆长度，单位：m。"
    )
    shotcrete_thickness: float = Field(
        description="喷射混凝土厚度，单位：cm。"
    )
    equipment_config: list[str] = Field(
        description="推荐的机械装备列表"
    )
    reasoning: str = Field(
        description="决策依据摘要"
    )
