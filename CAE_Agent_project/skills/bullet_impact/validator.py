def validate(params: dict) -> list[str]:
    """子弹冲击物理规则校验"""
    error_msgs = []
    
    geom = params.get("geometry", {})
    mat = params.get("material", {})
    phys = params.get("physics", {})

    plate_thickness = geom.get("plate_thickness", 1)
    if plate_thickness is None or plate_thickness <= 0:
        error_msgs.append("错误：钢板厚度必须大于 0。")
    
    bullet_radius = geom.get("bullet_radius", 1)
    if bullet_radius is None or bullet_radius <= 0:
        error_msgs.append("错误：子弹半径必须为正数。")
    
    bullet_radius_val = geom.get("bullet_radius", 0)
    bullet_radius_val = bullet_radius_val if bullet_radius_val is not None else 0
    bullet_diameter = bullet_radius_val * 2
    plate_length = geom.get("plate_length", 9999)
    plate_length = plate_length if plate_length is not None else 9999
    if bullet_diameter > plate_length:
        error_msgs.append("错误：子弹直径超过了钢板尺寸。")
    
    elastic_modulus = mat.get("elastic_modulus", 1)
    if elastic_modulus is None or elastic_modulus <= 0:
        error_msgs.append("错误：弹性模量必须为正数。")  
    
    step_time = phys.get("step_time", 1)
    if step_time is None or step_time <= 0:
        error_msgs.append("错误：步长不能为负或零。")

    return error_msgs
