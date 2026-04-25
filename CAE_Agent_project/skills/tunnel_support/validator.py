def validate(params: dict) -> list[str]:
    """隧道支护专属校验逻辑"""
    error_msgs = []
    
    # 1. 锚杆长度校验
    anchor_len = params.get("anchor_length", 1)
    if anchor_len <= 0:
        error_msgs.append("错误：锚杆长度必须大于 0m。")
    elif anchor_len > 20:
        error_msgs.append("错误：系统锚杆长度通常不超过 20m，超量纲。")
    
    # 2. 喷射混凝土厚度校验
    shot_thickness = params.get("shotcrete_thickness", 1)
    if shot_thickness <= 0:
        error_msgs.append("错误：喷射混凝土厚度必须大于 0cm。")
    elif shot_thickness > 100:
        error_msgs.append("错误：喷射混凝土总厚度异常 (> 100cm)。")

    return error_msgs
