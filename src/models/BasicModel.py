from pydantic import model_validator
from sqlmodel import Field, SQLModel
from datetime import date, datetime, timedelta, timezone

# 定义北京时区（UTC+8）
beijing_timezone = timezone(timedelta(hours=8))

current_time = datetime.now(beijing_timezone)

class BasicModel(SQLModel):
    id: int = Field(default=None, primary_key=True, description="唯一标识ID")
    created_at: datetime = Field(default_factory=current_time, description="创建时间")
    updated_at: datetime = Field(default_factory=current_time, description="更新时间")
    create_by: str = Field(default=None, description="创建者")
    update_by: str = Field(default=None, description="更新者")

    class Config:
        json_encoders = {
            # 若为datetime类型，格式化为“年-月-日 时:分:秒”，若为None则保持None
            datetime: lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None,
            # 若为date类型，格式化为“年-月-日”，若为None则保持None
            date: lambda dt: dt.strftime("%Y-%m-%d") if dt else None,
        }
    # 
    @model_validator(mode="before")
    def parse_string_datetimes(cls, value: dict) -> datetime:
        if not value:
            return 
        # 处理datetime类型字段：将字符串格式的日期时间转换为datetime对象
        datetime_fields = {
            k: datetime.strptime(v, "%Y-%m-%d %H:%M:%S")  # 使用strptime解析字符串为datetime
            for k, v in value.items()  # 遍历输入数据的键值对
            if isinstance(v, str)  # 只处理值为字符串的项
                and k in cls.model_fields  # 键必须是模型中定义的字段
                and cls.model_fields[k].annotation is datetime  # 字段的注解类型是datetime
        }
        # 处理date类型字段：将字符串格式的日期转换为date对象（通过datetime解析后取date部分）
        date_fields = {
            k: datetime.strptime(v, "%Y-%m-%d").date()  # 使用strptime解析字符串为datetime后取date
            for k, v in value.items()  # 遍历输入数据的键值对
            if isinstance(v, str)  # 只处理值为字符串的项
                and k in cls.model_fields  # 键必须是模型中定义的字段
                and cls.model_fields[k].annotation is date  # 字段的注解类型是date
        }
        result = {**value, **datetime_fields, **date_fields}
        
        return result